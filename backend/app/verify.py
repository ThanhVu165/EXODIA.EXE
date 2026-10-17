"""Verify chạy ĐÚNG đường nghiệp vụ thật: cùng service.process_email, cùng agent, cùng gate, cùng DB.
Không cache kết quả, không mock LLM, không nhánh theo mã ca. Kết quả mỗi lần chạy lưu vào bảng verify_runs.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from . import budget, service
from .service import Ctx, ServiceError
from .verify_checks import evaluate, load_cases

# Email dùng cho bảng kiểm tra điều khiển — DO AGENT VIẾT (giả lập), không lấy từ ground truth.
CONTROL_EMAIL = ("Cho em hỏi theo quy định của trường thì công cụ sửa ngữ pháp như Grammarly được xếp vào loại AI "
                 "nào ạ? (email kiểm tra điều khiển — dữ liệu giả lập)")
CONTROL_EMAIL_OTHER = "Nội dung khác hẳn để thử dùng lại khóa idempotency (dữ liệu giả lập)."
CONTROL_EMAIL_PAUSE = "Email gửi trong lúc hệ thống tạm dừng (kiểm tra điều khiển — dữ liệu giả lập)."
AUDIT_REQUIRED = ["case_id", "at", "actor", "action", "input_ref", "reason", "clause_ids", "status_before",
                  "status_after", "idempotency_key", "model_id", "policy_version"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cost(ctx: Ctx, usage: dict) -> float | None:
    pi, po = ctx.settings.price_input_per_1m, ctx.settings.price_output_per_1m
    if pi is None or po is None:
        return None
    return round(usage.get("input_tokens", 0) * pi / 1e6 + usage.get("output_tokens", 0) * po / 1e6, 6)


async def _start(ctx: Ctx, kind: str) -> tuple[uuid.UUID, datetime]:
    run_id, started = uuid.uuid4(), datetime.now(timezone.utc)
    async with ctx.db.connection() as conn:
        await conn.execute("INSERT INTO verify_runs (id, kind, started_at, status) VALUES (%s,%s,%s,'RUNNING')",
                           (run_id, kind, started))
    return run_id, started


async def _finish(ctx: Ctx, run_id, started, rows: list[dict], usage: dict, error: str | None = None) -> dict:
    finished = datetime.now(timezone.utc)
    duration = int((finished - started).total_seconds() * 1000)
    passed = sum(1 for r in rows if r.get("passed"))
    summary = {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
               "total_tokens": usage.get("total_tokens", 0), "estimated_cost_usd": _cost(ctx, usage),
               "cost_note": None if _cost(ctx, usage) is not None else "Chưa cấu hình PRICE_INPUT_PER_1M/PRICE_OUTPUT_PER_1M"}
    async with ctx.db.connection() as conn:
        await conn.execute(
            """UPDATE verify_runs SET finished_at=%s, duration_ms=%s, status=%s, passed=%s, total=%s,
                      results=%s, usage=%s, error=%s WHERE id=%s""",
            (finished, duration, "FAILED" if error else "DONE", passed, len(rows),
             Jsonb(service.to_json(rows)), Jsonb(summary), error, run_id))
    import logging
    logging.getLogger("dsa.verify").info("verify run %s: %s/%s đạt, token=%s, chi phí ước tính=%s",
                                         run_id, passed, len(rows), summary["total_tokens"],
                                         summary["estimated_cost_usd"])
    return {"run_id": str(run_id), "started_at": started.isoformat(), "finished_at": finished.isoformat(),
            "duration_ms": duration, "passed": passed, "total": len(rows), "results": service.to_json(rows),
            "usage": summary, "error": error}


async def run_cases(ctx: Ctx, kind: str) -> dict:
    doc = load_cases()
    set_name = {"GENERAL": "general_verify", "ESCALATION": "escalation_verify"}[kind]
    run_id, started = await _start(ctx, kind)
    rows, usage = [], {}
    for cid in doc["verify_sets"][set_name]:
        spec = doc["by_id"][cid]
        t0 = time.perf_counter()
        case, _ = await service.process_email(
            ctx, body=spec["email"], sender=None, key=f"verify:{run_id}:{cid}", source="VERIFY",
            verify_run_id=run_id, budget_bucket=budget.BUCKET_LLM_VERIFY)
        d = await service.case_detail(ctx, case["id"])
        row = evaluate(spec, d["case"], d["outbox"], ctx.policy, doc["generic_question_patterns"])
        row["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        row["finished_at"] = _now()
        for k, v in (d["case"].get("usage") or {}).items():
            usage[k] = usage.get(k, 0) + v
        rows.append(row)
    return await _finish(ctx, run_id, started, rows, usage)


async def _count(ctx: Ctx, sql: str, *args) -> int:
    async with ctx.db.connection() as conn:
        cur = await conn.execute(sql, args)
        return (await cur.fetchone())["n"]


INTERNAL_SCOPE_KEY = "dsa_internal_verify_run"


class _InternalVerifyApp:
    """Bọc ASGI chỉ dùng trong tiến trình: gắn run_id Verify vào scope. Request từ mạng không đi qua lớp này."""

    def __init__(self, app, run_id: uuid.UUID) -> None:
        self.app, self.run_id = app, run_id

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope[INTERNAL_SCOPE_KEY] = self.run_id
        await self.app(scope, receive, send)


async def run_controls(ctx: Ctx, app) -> dict:
    """Bảng kiểm tra điều khiển: các bước 1–3, 5–8 gửi HTTP THẬT tới các route của chính ứng dụng (ASGI trong
    tiến trình, đi qua đúng FastAPI routing/validation/handler), rồi đếm dòng trong DB.
    Bước 4 cần chèn lỗi giữa transaction nên dùng hook trong tiến trình (mode=in-process), không lộ endpoint."""
    import httpx

    run_id, started = await _start(ctx, "CONTROLS")
    rows: list[dict] = []
    usage: dict = {}

    def add(no, name, ok, evidence, mode="http"):
        rows.append({"no": no, "check": name, "passed": bool(ok), "evidence": evidence, "mode": mode,
                     "at": _now()})

    def acc(case):
        for k, v in (case.get("usage") or {}).items():
            usage[k] = usage.get(k, 0) + v

    async with ctx.db.connection() as conn:
        was_paused = await service.is_paused(conn)
    if was_paused:
        return await _finish(ctx, run_id, started, [{"no": 0, "check": "Hệ thống đang tạm dừng", "passed": False,
                             "evidence": "Tắt tạm dừng trước khi chạy kiểm tra điều khiển", "mode": "-"}], usage)

    transport = httpx.ASGITransport(app=_InternalVerifyApp(app, run_id))
    client = httpx.AsyncClient(transport=transport, base_url="http://verify.internal", timeout=300)

    async def post_email(body, key):
        r = await client.post("/api/emails", json={"body": body}, headers={"Idempotency-Key": key})
        return r, (r.json().get("case") if r.headers.get("content-type", "").startswith("application/json") else None)

    error = None
    try:
        k1 = f"verify:{run_id}:ctl1"
        # 1. cùng khóa + cùng nội dung -> 1 ca, 1 outbox
        r1, c1 = await post_email(CONTROL_EMAIL, k1)
        acc(c1 or {})
        r1b, c1b = await post_email(CONTROL_EMAIL, k1)
        n_cases = await _count(ctx, "SELECT count(*) n FROM cases WHERE submission_key=%s", k1)
        n_out = await _count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", c1["id"])
        add(1, "Cùng khóa + cùng nội dung → 1 ca, 1 outbox",
            r1.status_code == 201 and r1b.status_code == 200 and c1b["id"] == c1["id"] and n_cases == 1 and n_out == 1,
            f"HTTP {r1.status_code} rồi {r1b.status_code}; ca={n_cases}, outbox={n_out}, quyết định={c1['decision']}, "
            f"trạng thái={c1['status']}" + ("" if c1["decision"] == "AUTO" else " — ca kiểm tra không AUTO nên không có outbox"))

        # 2. cùng khóa + nội dung khác -> 409
        r2, _ = await post_email(CONTROL_EMAIL_OTHER, k1)
        add(2, "Cùng khóa + nội dung khác → 409", r2.status_code == 409,
            f"HTTP {r2.status_code} {r2.json().get('error', {}).get('code')}")

        # 3. cùng nội dung + khóa mới -> 2 ca, có NGHI_TRUNG
        r3, c3 = await post_email(CONTROL_EMAIL, f"verify:{run_id}:ctl3")
        acc(c3 or {})
        n_same = await _count(ctx, "SELECT count(*) n FROM cases WHERE verify_run_id=%s AND content_hash=%s",
                              run_id, service.content_hash(None, CONTROL_EMAIL))
        add(3, "Cùng nội dung + khóa mới → 2 ca, cờ NGHI_TRUNG",
            r3.status_code == 201 and n_same == 2 and "NGHI_TRUNG" in c3["flags"],
            f"HTTP {r3.status_code}; số ca cùng nội dung={n_same}, cờ ca mới={c3['flags']}")

        # 4. lỗi chèn giữa chừng rồi retry -> đúng 1 outbox (hook trong tiến trình)
        k4 = f"verify:{run_id}:ctl4"

        async def boom(point):
            raise RuntimeError(f"lỗi giả lập tại {point} (hook kiểm tra, chỉ trong tiến trình)")
        c4, _ = await service.process_email(ctx, body=CONTROL_EMAIL, sender=None, key=k4, source="VERIFY",
                                            verify_run_id=run_id, budget_bucket=budget.BUCKET_LLM_VERIFY,
                                            fault_hook=boom)
        acc(c4)
        mid_out = await _count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", c4["id"])
        r4 = await client.post(f"/api/cases/{c4['id']}/retry")
        c4b = r4.json().get("case") or {}
        end_out = await _count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", c4["id"])
        add(4, "Retry sau lỗi chèn giữa chừng → đúng 1 outbox",
            c4["status"] == "ERROR" and mid_out == 0 and end_out == 1 and c4b.get("status") == "AUTO_REPLIED",
            f"sau lỗi: {c4['status']}/{c4['error_code']}, outbox={mid_out}; retry qua HTTP {r4.status_code}: "
            f"{c4b.get('status')}, outbox={end_out}", mode="in-process (lỗi) + http (retry)")

        # 5. tạm dừng -> không AUTO, vào hàng chờ với PAUSED; rồi tắt
        rp = await client.post("/api/system/pause", json={"on": True, "reason": "Verify: kiểm tra điều khiển số 5",
                                                          "actor_name": "verify"})
        try:
            r5, c5 = await post_email(CONTROL_EMAIL_PAUSE + f" [{run_id}]", f"verify:{run_id}:ctl5")
        finally:
            ru = await client.post("/api/system/pause", json={"on": False, "reason": "Verify: kết thúc kiểm tra số 5",
                                                              "actor_name": "verify"})
        add(5, "Bật tạm dừng → không AUTO, vào hàng chờ với PAUSED; sau đó tắt",
            rp.status_code == 200 and ru.status_code == 200 and c5["status"] == "PENDING_HUMAN" and "PAUSED" in c5["flags"],
            f"bật HTTP {rp.status_code}; ca: {c5['status']}, cờ={c5['flags']}; tắt HTTP {ru.status_code}")

        # 6. hủy ca chưa kết thúc -> CANCELLED + audit
        r6 = await client.post(f"/api/cases/{c5['id']}/cancel",
                               json={"reason": "Verify: kiểm tra hủy (số 6)", "actor_name": "verify"})
        c6 = r6.json().get("case") or {}
        n_aud = await _count(ctx, "SELECT count(*) n FROM audit_log WHERE case_id=%s AND action='CANCELLED'", c5["id"])
        add(6, "Hủy ca chưa kết thúc → CANCELLED, có audit", r6.status_code == 200 and c6.get("status") == "CANCELLED"
            and n_aud == 1, f"HTTP {r6.status_code}; trạng thái={c6.get('status')}, dòng audit CANCELLED={n_aud}")

        # 7. override ca AUTO -> đính chính, bản cũ SUPERSEDED, có lý do
        if c1["status"] == "AUTO_REPLIED":
            r7 = await client.post(f"/api/cases/{c1['id']}/override",
                                   json={"body": "Đính chính (Verify): nội dung bổ sung.",
                                         "reason": "Verify: kiểm tra override (số 7)", "actor_name": "verify"},
                                   headers={"Idempotency-Key": f"verify:{run_id}:ctl7"})
            async with ctx.db.connection() as conn:
                cur = await conn.execute("SELECT kind, status, supersedes_id FROM outbox WHERE case_id=%s "
                                         "ORDER BY created_at", (c1["id"],))
                obs = await cur.fetchall()
                cur = await conn.execute("SELECT reason FROM audit_log WHERE case_id=%s AND action='OVERRIDE_CORRECTION'",
                                         (c1["id"],))
                ov = await cur.fetchone()
            ok = (r7.status_code == 200 and (r7.json().get("case") or {}).get("status") == "SUPERSEDED"
                  and [(o["kind"], o["status"]) for o in obs] == [("AUTO_REPLY", "SUPERSEDED"), ("CORRECTION", "SENT")]
                  and obs[1]["supersedes_id"] and ov and ov["reason"])
            add(7, "Override ca AUTO → đính chính, bản cũ SUPERSEDED, có lý do", ok,
                f"HTTP {r7.status_code}; outbox={[(o['kind'], o['status']) for o in obs]}, "
                f"lý do='{ov['reason'] if ov else None}'")
        else:
            add(7, "Override ca AUTO → đính chính, bản cũ SUPERSEDED, có lý do", False,
                f"không thực hiện được: ca kiểm tra không ở AUTO_REPLIED (thực: {c1['status']})")

        # 8. audit đầy đủ cho một ca (đọc qua API)
        r8 = await client.get(f"/api/cases/{c1['id']}")
        audit_rows = r8.json().get("audit") or []
        decided = [a for a in audit_rows if a["action"].startswith("DECIDED_")]
        missing = [f for f in AUDIT_REQUIRED if not decided or decided[0].get(f) in (None, "", [])]
        base_missing = sorted({f for a in audit_rows for f in ("case_id", "at", "actor", "action", "input_ref",
                                                                "policy_version") if not a.get(f)})
        add(8, "Audit đầy đủ cho một ca (đủ trường Mục 6.3)",
            r8.status_code == 200 and decided and not missing and not base_missing,
            f"HTTP {r8.status_code}; {len(audit_rows)} dòng: {[a['action'] for a in audit_rows]}; "
            f"trường thiếu ở dòng quyết định: {missing or 'không'}; ở các dòng: {base_missing or 'không'}")
    except Exception as exc:   # báo nguyên văn, không nuốt
        error = f"{type(exc).__name__}: {exc}"
    finally:
        async with ctx.db.connection() as conn:
            still_paused = await service.is_paused(conn)
        if still_paused and not was_paused:
            await service.set_paused(ctx, False, "Verify: khôi phục sau lỗi", "verify")
        await client.aclose()
    return await _finish(ctx, run_id, started, rows, usage, error)


async def latest_runs(ctx: Ctx, limit: int = 10) -> list[dict]:
    async with ctx.db.connection() as conn:
        cur = await conn.execute("SELECT * FROM verify_runs ORDER BY started_at DESC LIMIT %s", (limit,))
        return service.to_json(await cur.fetchall())
