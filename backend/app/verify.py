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


async def run_controls(ctx: Ctx) -> dict:
    """Bảng kiểm tra điều khiển. Gọi CÙNG các hàm service mà API dùng (mode=service), đếm dòng trong DB.
    Kiểm tra 4 dùng hook lỗi trong tiến trình (mode=in-process), không lộ ra endpoint công khai."""
    run_id, started = await _start(ctx, "CONTROLS")
    rows: list[dict] = []
    usage: dict = {}

    def add(no, name, ok, evidence, mode="service"):
        rows.append({"no": no, "check": name, "passed": bool(ok), "evidence": evidence, "mode": mode,
                     "at": _now()})

    def acc(case):
        for k, v in (case.get("usage") or {}).items():
            usage[k] = usage.get(k, 0) + v

    async def process(body, key, **kw):
        return await service.process_email(ctx, body=body, sender=None, key=key, source="VERIFY",
                                           verify_run_id=run_id, budget_bucket=budget.BUCKET_LLM_VERIFY, **kw)

    async with ctx.db.connection() as conn:
        was_paused = await service.is_paused(conn)
    if was_paused:
        return await _finish(ctx, run_id, started, [{"no": 0, "check": "Hệ thống đang tạm dừng", "passed": False,
                             "evidence": "Tắt tạm dừng trước khi chạy kiểm tra điều khiển", "mode": "-"}], usage)
    k1 = f"verify:{run_id}:ctl1"
    try:
        # 1. cùng khóa + cùng nội dung -> 1 ca, 1 outbox
        c1, _ = await process(CONTROL_EMAIL, k1)
        acc(c1)
        c1b, created_b = await process(CONTROL_EMAIL, k1)
        n_cases = await _count(ctx, "SELECT count(*) n FROM cases WHERE submission_key=%s", k1)
        n_out = await _count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", c1["id"])
        add(1, "Cùng khóa + cùng nội dung → 1 ca, 1 outbox", n_cases == 1 and n_out == 1 and not created_b,
            f"ca={n_cases}, outbox={n_out}, quyết định={c1['decision']}, trạng thái={c1['status']}"
            + ("" if c1["decision"] == "AUTO" else " — ca kiểm tra không AUTO nên không có outbox"))

        # 2. cùng khóa + nội dung khác -> 409
        try:
            await process(CONTROL_EMAIL_OTHER, k1)
            add(2, "Cùng khóa + nội dung khác → 409", False, "không bị từ chối")
        except ServiceError as e:
            add(2, "Cùng khóa + nội dung khác → 409", e.http_status == 409, f"HTTP {e.http_status} {e.code}")

        # 3. cùng nội dung + khóa mới -> 2 ca, có NGHI_TRUNG
        c3, _ = await process(CONTROL_EMAIL, f"verify:{run_id}:ctl3")
        acc(c3)
        n_same = await _count(ctx, "SELECT count(*) n FROM cases WHERE verify_run_id=%s AND content_hash=%s",
                              run_id, c1["content_hash"])
        add(3, "Cùng nội dung + khóa mới → 2 ca, cờ NGHI_TRUNG", n_same == 2 and "NGHI_TRUNG" in c3["flags"],
            f"số ca cùng nội dung={n_same}, cờ ca mới={c3['flags']}")

        # 4. lỗi chèn giữa chừng rồi retry -> đúng 1 outbox
        k4 = f"verify:{run_id}:ctl4"

        async def boom(point):
            raise RuntimeError(f"lỗi giả lập tại {point} (hook kiểm tra, chỉ trong tiến trình)")
        c4, _ = await process(CONTROL_EMAIL, k4, fault_hook=boom)
        acc(c4)
        mid_out = await _count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", c4["id"])
        c4b, _ = await process(CONTROL_EMAIL, k4)
        end_out = await _count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", c4["id"])
        add(4, "Retry sau lỗi chèn giữa chừng → đúng 1 outbox",
            c4["status"] == "ERROR" and mid_out == 0 and end_out == 1 and c4b["status"] == "AUTO_REPLIED",
            f"sau lỗi: {c4['status']}/{c4['error_code']}, outbox={mid_out}; sau retry: {c4b['status']}, outbox={end_out}",
            mode="in-process")

        # 5. tạm dừng -> không AUTO, vào hàng chờ với PAUSED; rồi tắt
        await service.set_paused(ctx, True, "Verify: kiểm tra điều khiển số 5", "verify")
        try:
            c5, _ = await process(CONTROL_EMAIL_PAUSE + f" [{run_id}]", f"verify:{run_id}:ctl5")
        finally:
            await service.set_paused(ctx, False, "Verify: kết thúc kiểm tra số 5", "verify")
        add(5, "Bật tạm dừng → không AUTO, vào hàng chờ với PAUSED; sau đó tắt",
            c5["status"] == "PENDING_HUMAN" and "PAUSED" in c5["flags"],
            f"trạng thái={c5['status']}, cờ={c5['flags']}, đã tắt tạm dừng")

        # 6. hủy ca chưa kết thúc -> CANCELLED + audit
        c6 = await service.cancel_case(ctx, c5["id"], "Verify: kiểm tra hủy (số 6)", "verify")
        n_aud = await _count(ctx, "SELECT count(*) n FROM audit_log WHERE case_id=%s AND action='CANCELLED'", c5["id"])
        add(6, "Hủy ca chưa kết thúc → CANCELLED, có audit", c6["status"] == "CANCELLED" and n_aud == 1,
            f"trạng thái={c6['status']}, dòng audit CANCELLED={n_aud}")

        # 7. override ca AUTO -> đính chính, bản cũ SUPERSEDED, có lý do
        if c1["status"] == "AUTO_REPLIED":
            c7 = await service.override_auto(ctx, c1["id"], "Đính chính (Verify): nội dung bổ sung.",
                                             "Verify: kiểm tra override (số 7)", f"verify:{run_id}:ctl7", "verify")
            async with ctx.db.connection() as conn:
                cur = await conn.execute("SELECT kind, status, supersedes_id FROM outbox WHERE case_id=%s "
                                         "ORDER BY created_at", (c1["id"],))
                obs = await cur.fetchall()
                cur = await conn.execute("SELECT reason FROM audit_log WHERE case_id=%s AND action='OVERRIDE_CORRECTION'",
                                         (c1["id"],))
                ov = await cur.fetchone()
            ok = (c7["status"] == "SUPERSEDED" and [(o["kind"], o["status"]) for o in obs] ==
                  [("AUTO_REPLY", "SUPERSEDED"), ("CORRECTION", "SENT")] and obs[1]["supersedes_id"] and ov and ov["reason"])
            add(7, "Override ca AUTO → đính chính, bản cũ SUPERSEDED, có lý do", ok,
                f"outbox={[(o['kind'], o['status']) for o in obs]}, lý do='{ov['reason'] if ov else None}'")
        else:
            add(7, "Override ca AUTO → đính chính, bản cũ SUPERSEDED, có lý do", False,
                f"không thực hiện được: ca kiểm tra không ở AUTO_REPLIED (thực: {c1['status']})")

        # 8. audit đầy đủ cho một ca
        d = await service.case_detail(ctx, c1["id"])
        decided = [a for a in d["audit"] if a["action"].startswith("DECIDED_")]
        missing = [f for f in AUDIT_REQUIRED if not decided or decided[0].get(f) in (None, "", [])]
        base_missing = sorted({f for a in d["audit"] for f in ("case_id", "at", "actor", "action", "input_ref",
                                                                "policy_version") if not a.get(f)})
        add(8, "Audit đầy đủ cho một ca (đủ trường Mục 6.3)", decided and not missing and not base_missing,
            f"{len(d['audit'])} dòng: {[a['action'] for a in d['audit']]}; trường thiếu ở dòng quyết định: "
            f"{missing or 'không'}; trường thiếu ở các dòng: {base_missing or 'không'}")
        error = None
    except Exception as exc:   # báo nguyên văn, không nuốt
        error = f"{type(exc).__name__}: {exc}"
        async with ctx.db.connection() as conn:
            if await service.is_paused(conn) and not was_paused:
                await service.set_paused(ctx, False, "Verify: khôi phục sau lỗi", "verify")
    return await _finish(ctx, run_id, started, rows, usage, error)


async def latest_runs(ctx: Ctx, limit: int = 10) -> list[dict]:
    async with ctx.db.connection() as conn:
        cur = await conn.execute("SELECT * FROM verify_runs ORDER BY started_at DESC LIMIT %s", (limit,))
        return service.to_json(await cur.fetchall())
