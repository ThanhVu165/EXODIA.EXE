"""Dịch vụ nghiệp vụ: xử lý email, idempotency, audit, tạm dừng/hủy/override.

Mọi chuyển trạng thái là cập nhật CÓ ĐIỀU KIỆN nguyên tử trong Postgres; không dựa vào khóa trong tiến trình.
Endpoint công khai và Verify đều đi qua CÙNG các hàm ở đây.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

from psycopg.types.json import Jsonb

from . import budget
from .agent import AgentResult, AgentRunner, AgentTechnicalError
from .config import Settings
from .db import Database
from .gate import (REASON_LABEL_VI, ROUTE_LABEL_VI, GateDecision, IncompleteOutput, decide,
                   validate)
from .policy import Policy, normalize
from .prefilter import detect_injection

log = logging.getLogger("dsa.service")

TERMINAL = {"AUTO_REPLIED", "HUMAN_REPLIED", "CANCELLED", "SUPERSEDED"}
CANCELLABLE = ("RECEIVED", "PROCESSING", "PENDING_HUMAN")
DUP_WINDOW = "24 hours"

FaultHook = Callable[[str], Awaitable[None]]


class ServiceError(Exception):
    def __init__(self, http_status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message


@dataclass
class Ctx:
    db: Database
    policy: Policy
    settings: Settings
    agent: AgentRunner | None


def content_hash(sender: str | None, body: str) -> str:
    return hashlib.sha256((normalize(sender or "").casefold() + "\n" + normalize(body)).encode()).hexdigest()


def input_ref(case: dict) -> str:
    return f"case:{case['id']} sha256:{case['content_hash'][:16]}"


async def audit(conn, ctx: Ctx, case: dict | None, action: str, *, actor: str = "system",
                actor_name: str | None = None, reason: str | None = None, clause_ids: list[str] | None = None,
                before: str | None = None, after: str | None = None, key: str | None = None,
                model_id: str | None = None, details: dict | None = None) -> None:
    await conn.execute(
        """INSERT INTO audit_log (case_id, actor, actor_name, action, input_ref, reason, clause_ids,
                                  status_before, status_after, idempotency_key, model_id, policy_version, details)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (case["id"] if case else None, actor, actor_name, action, input_ref(case) if case else None, reason,
         clause_ids or [], before, after, key, model_id or (case or {}).get("model_id"),
         ctx.policy.version, Jsonb(details) if details is not None else None))


async def get_case(conn, case_id) -> dict | None:
    cur = await conn.execute("SELECT * FROM cases WHERE id=%s", (case_id,))
    return await cur.fetchone()


async def is_paused(conn) -> bool:
    cur = await conn.execute("SELECT value FROM system_flags WHERE key='paused'")
    row = await cur.fetchone()
    return bool(row and row["value"].get("on"))


# ----------------------------------------------------------------------------------------------------------
# Tiếp nhận + idempotency lớp 1 (khóa theo lần gửi) và lớp 2 (cờ NGHI_TRUNG)
# ----------------------------------------------------------------------------------------------------------
async def receive(ctx: Ctx, *, body: str, sender: str | None, key: str, source: str,
                  verify_run_id: uuid.UUID | None) -> tuple[dict, bool]:
    if not key or len(key) > 200:
        raise ServiceError(400, "BAD_IDEMPOTENCY_KEY", "Thiếu hoặc sai header Idempotency-Key")
    if not body or not body.strip():
        raise ServiceError(400, "EMPTY_EMAIL", "Nội dung email trống")
    if len(body) > ctx.settings.max_email_chars:
        raise ServiceError(413, "EMAIL_TOO_LONG", f"Email dài quá {ctx.settings.max_email_chars} ký tự")
    h = content_hash(sender, body)
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """INSERT INTO cases (id, submission_key, content_hash, sender, email_body, source, verify_run_id,
                                      status, policy_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'RECEIVED',%s)
                   ON CONFLICT (submission_key) DO NOTHING RETURNING *""",
                (uuid.uuid4(), key, h, sender, body, source, verify_run_id, ctx.policy.version))
            case = await cur.fetchone()
            if case is None:
                cur = await conn.execute("SELECT * FROM cases WHERE submission_key=%s", (key,))
                existing = await cur.fetchone()
                if existing["content_hash"] != h:
                    raise ServiceError(409, "IDEMPOTENCY_KEY_REUSED",
                                       "Khóa Idempotency-Key đã dùng cho một nội dung khác")
                return existing, False
            # Lớp 2: trùng nội dung trong khung thời gian, cùng nguồn (Verify chỉ so trong cùng lần chạy).
            cur = await conn.execute(
                f"""SELECT count(*) AS n FROM cases WHERE content_hash=%s AND id<>%s AND source=%s
                       AND verify_run_id IS NOT DISTINCT FROM %s AND created_at > now() - interval '{DUP_WINDOW}'""",
                (h, case["id"], source, verify_run_id))
            if (await cur.fetchone())["n"] > 0:
                cur = await conn.execute(
                    "UPDATE cases SET flags = array_append(flags, 'NGHI_TRUNG') WHERE id=%s RETURNING *", (case["id"],))
                case = await cur.fetchone()
            await audit(conn, ctx, case, "RECEIVED", reason="Tiếp nhận email mới (lời sinh viên, chưa xác minh)",
                        after="RECEIVED", key=key,
                        details={"source": source, "flags": case["flags"]})
    return case, True


async def claim(ctx: Ctx, case_id) -> dict | None:
    """RECEIVED/ERROR -> PROCESSING, hoặc tiếp quản PROCESSING đã hết lease. None nếu không giành được."""
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM cases WHERE id=%s FOR UPDATE", (case_id,))
            before = await cur.fetchone()
            cur = await conn.execute(
                f"""UPDATE cases SET status='PROCESSING', attempts=attempts+1, error_code=NULL, error_detail=NULL,
                           lease_until=now() + interval '{int(ctx.settings.lease_seconds)} seconds', updated_at=now()
                    WHERE id=%s AND (status IN ('RECEIVED','ERROR')
                                     OR (status='PROCESSING' AND lease_until < now()))
                    RETURNING *""", (case_id,))
            case = await cur.fetchone()
            if case:
                await audit(conn, ctx, case, "CLAIMED", reason=f"Bắt đầu xử lý (lần thử {case['attempts']})",
                            before=before["status"], after="PROCESSING",
                            key=case["submission_key"], details={"attempt": case["attempts"]})
            return case


async def mark_error(ctx: Ctx, case: dict, code: str, detail: str, extra_flags: list[str] | None = None) -> dict:
    flags = list(dict.fromkeys(list(case.get("flags") or []) + (extra_flags or [])))
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """UPDATE cases SET status='ERROR', error_code=%s, error_detail=%s, flags=%s, lease_until=NULL,
                          updated_at=now()
                   WHERE id=%s AND status='PROCESSING' RETURNING *""", (code, detail[:1000], flags, case["id"]))
            row = await cur.fetchone()
            if row:
                await audit(conn, ctx, row, "TECHNICAL_ERROR", reason=f"{code}: {detail[:300]}",
                            before="PROCESSING", after="ERROR", key=row["submission_key"])
                return row
            return await get_case(conn, case["id"])


# ----------------------------------------------------------------------------------------------------------
# Xử lý chính
# ----------------------------------------------------------------------------------------------------------
async def process_email(ctx: Ctx, *, body: str, sender: str | None, key: str, source: str = "PUBLIC",
                        verify_run_id: uuid.UUID | None = None, budget_bucket: str = budget.BUCKET_LLM_PUBLIC,
                        fault_hook: FaultHook | None = None) -> tuple[dict, bool]:
    """Trả (ca, created). Không bao giờ tạo outbox khi có lỗi kỹ thuật."""
    case, created = await receive(ctx, body=body, sender=sender, key=key, source=source,
                                  verify_run_id=verify_run_id)
    claimed = await claim(ctx, case["id"])
    if claimed is None:
        return case, created   # replay idempotent: trả kết quả hiện có, không xử lý lại
    case = claimed

    async with ctx.db.connection() as conn:
        paused = await is_paused(conn)
    if paused:
        return await finalize_paused(ctx, case), created

    # Tái dùng đầu ra agent đã validate của chính ca này (retry bước thực thi, không gọi lại LLM).
    reuse = case["agent_output"] is not None and case["policy_version"] == ctx.policy.version
    prefilter_hits = detect_injection(body)
    try:
        if reuse:
            from .agent_contract import AgentOutput
            out = AgentOutput.model_validate(case["agent_output"])
            result = AgentResult(out, case["model_id"], case["usage"] or {}, 0)
            content_errors: list[str] = []
            async with ctx.db.connection() as conn:
                async with conn.transaction():
                    await audit(conn, ctx, case, "AGENT_OUTPUT_REUSED", reason="retry bước thực thi",
                                before="PROCESSING", after="PROCESSING", key=case["submission_key"])
        else:
            result, content_errors = await _run_agent_with_retry(ctx, case, body, budget_bucket)
    except AgentTechnicalError as exc:
        # Lỗi kỹ thuật => ERROR (không AUTO). Nếu tiền lọc đã nghi injection, vẫn gắn cờ để nhân viên thấy.
        return await mark_error(ctx, case, exc.code, exc.detail,
                                ["SUSPECT_INPUT"] if prefilter_hits else None), created
    except Exception as exc:  # lỗi bất ngờ (DB...) => ERROR, ghi nguyên văn loại lỗi
        log.exception("Lỗi không lường trước khi gọi agent")
        return await mark_error(ctx, case, "INTERNAL_ERROR", f"{type(exc).__name__}: {exc}"), created

    try:
        decision = decide(result.output, prefilter_hits, content_errors)
    except IncompleteOutput as exc:
        return await mark_error(ctx, case, "AGENT_OUTPUT_INCOMPLETE", str(exc)), created

    try:
        final = await finalize(ctx, case, result, decision, prefilter_hits, fault_hook)
    except Exception as exc:
        log.exception("Finalize thất bại")
        return await mark_error(ctx, case, "FINALIZE_FAILED", f"{type(exc).__name__}: {exc}"), created
    return final, created


async def _consume_llm(ctx: Ctx, bucket: str) -> None:
    limit = ctx.settings.verify_daily_cap if bucket == budget.BUCKET_LLM_VERIFY else ctx.settings.llm_daily_cap
    async with ctx.db.connection() as conn:
        ok = await budget.consume(conn, bucket, "day", limit)
    if not ok:
        raise AgentTechnicalError("BUDGET_EXCEEDED", f"Đã chạm trần {limit} lượt gọi LLM/ngày ({bucket})")


async def _run_agent_with_retry(ctx: Ctx, case: dict, body: str, bucket: str) -> tuple[AgentResult, list[str]]:
    if ctx.agent is None:
        raise AgentTechnicalError("LLM_NOT_CONFIGURED", "OPENAI_MODEL/OPENAI_API_KEY chưa cấu hình")
    usage_total: dict = {}
    feedback = None
    for attempt in (1, 2):   # tối đa MỘT lần retry có chủ đích
        await _consume_llm(ctx, bucket)
        result = await ctx.agent.run(body, feedback)
        for k, v in result.usage.items():
            usage_total[k] = usage_total.get(k, 0) + v
        code_errors, content_errors = validate(result.output, ctx.policy)
        async with ctx.db.connection() as conn:
            async with conn.transaction():
                await audit(conn, ctx, case, "AGENT_CALLED",
                            reason=("Gọi trợ lý AI để trích xuất, tìm căn cứ, soạn nháp (không có quyền duyệt)"
                                    + (f"; lỗi đầu ra: {code_errors + content_errors}" if code_errors or content_errors else "")),
                            before="PROCESSING", after="PROCESSING",
                            key=case["submission_key"], model_id=result.model_id,
                            clause_ids=list(result.output.cites) + list(result.output.policy_gap_ids),
                            details={"attempt": attempt, "latency_ms": result.latency_ms, "usage": result.usage,
                                     "validation_errors": code_errors + content_errors,
                                     "signals": result.output.signals.model_dump()})
        if not code_errors and not content_errors:
            break
        feedback = "; ".join(code_errors + content_errors)
    result.usage = usage_total
    if code_errors:
        raise AgentTechnicalError("INVALID_CLAUSE_CODE", "; ".join(code_errors))
    # Lưu đầu ra đã validate trước khi finalize => retry finalize không gọi lại LLM.
    async with ctx.db.connection() as conn:
        await conn.execute(
            """UPDATE cases SET agent_output=%s, model_id=%s, usage=%s, policy_version=%s, updated_at=now()
               WHERE id=%s AND status='PROCESSING'""",
            (Jsonb(result.output.model_dump(mode="json")), result.model_id, Jsonb(usage_total),
             ctx.policy.version, case["id"]))
    return result, content_errors


def _excerpts(ctx: Ctx, codes: list[str]) -> list[dict]:
    seen, out = set(), []
    for c in codes:
        if c in seen or not ctx.policy.is_valid_id(c):
            continue
        seen.add(c)
        out.append(ctx.policy.excerpt(c))
    return out


def build_package(ctx: Ctx, result: AgentResult, d: GateDecision, prefilter_hits: list[str]) -> dict:
    o = result.output
    if d.decision == "AUTO":
        why = "Bộ quy tắc (code) cho phép trả lời tự động: không có lý do chuyển tiếp, không có cờ nghi vấn, " \
              "có căn cứ điều khoản hợp lệ và bản trả lời qua kiểm tra cụm cấm."
    elif "SUSPECT_INPUT" in d.flags:
        why = "Email có dấu hiệu chỉ dẫn nhắm vào hệ thống (nghi vấn). Hệ thống không đưa ra kết quả khẳng định; " \
              "bản trả lời bị chặn và ca được chuyển cho nhân viên DSA."
    else:
        why = "Bộ quy tắc (code) chuyển cho nhân viên DSA vì: " + \
              "; ".join(REASON_LABEL_VI.get(r, r) for r in d.reasons) + "."
    return {
        "intent": o.intent,
        "cites": list(o.cites),
        "policy_gap_ids": list(o.policy_gap_ids),
        "student_said_unverified": o.stated_facts,
        "verified_from_policy": _excerpts(ctx, list(o.cites) + list(o.policy_gap_ids)),
        "unknown_facts": o.unknown_facts,
        "reasons": d.reasons,
        "reason_primary": d.reason_primary,
        "flags": d.flags,
        "signals": o.signals.model_dump(),
        "prefilter_hits": prefilter_hits,
        "suggested_reply": None if "SUSPECT_INPUT" in d.flags else o.draft_reply,
        "suggested_reply_blocked": "SUSPECT_INPUT" in d.flags,
        "handoff_question": d.handoff_question,
        "question_source": d.question_source,
        "suggested_route": o.suggested_route.value,
        "suggested_route_label": ROUTE_LABEL_VI.get(o.suggested_route.value),
        "gate_explanation": why,
        "plain_explanation": o.plain_explanation,
        "gate_notes": d.notes,
    }


def reply_with_footer(ctx: Ctx, text: str, cites: list[str]) -> str:
    locs = "; ".join(f"{c} ({ctx.policy.clauses[c].locator})" for c in cites if ctx.policy.is_valid_id(c))
    return (f"{text.strip()}\n\n—\nCăn cứ: Quy định kèm QĐ 4002/QĐ-ĐHKT-NCPTGKTC — {locs}.\n"
            "(Phản hồi tự động từ bản demo DSA Intelligence; dữ liệu giả lập, không phải hệ thống chính thức của UEH.)")


async def finalize(ctx: Ctx, case: dict, result: AgentResult, d: GateDecision, prefilter_hits: list[str],
                   fault_hook: FaultHook | None) -> dict:
    package = build_package(ctx, result, d, prefilter_hits)
    flags = list(dict.fromkeys(list(case["flags"]) + d.flags))
    clause_ids = list(result.output.cites) + list(result.output.policy_gap_ids)
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM cases WHERE id=%s FOR UPDATE", (case["id"],))
            current = await cur.fetchone()
            if current["status"] != "PROCESSING":
                return current     # bị hủy/tiếp quản trong lúc chạy: không ghi gì thêm
            if d.decision == "AUTO":
                cur = await conn.execute(
                    """INSERT INTO outbox (id, case_id, kind, version, body, status, idempotency_key)
                       VALUES (%s,%s,'AUTO_REPLY',1,%s,'SENT',%s)
                       ON CONFLICT DO NOTHING RETURNING id""",
                    (uuid.uuid4(), case["id"], reply_with_footer(ctx, d.reply, result.output.cites),
                     f"auto:{case['id']}"))
                outbox_row = await cur.fetchone()
                if fault_hook:
                    await fault_hook("after_outbox_insert")
                new_status = "AUTO_REPLIED"
            else:
                outbox_row = None
                new_status = "PENDING_HUMAN"
            cur = await conn.execute(
                """UPDATE cases SET status=%s, decision=%s, reason_primary=%s, reasons=%s, flags=%s, package=%s,
                          lease_until=NULL, updated_at=now()
                   WHERE id=%s AND status='PROCESSING' RETURNING *""",
                (new_status, d.decision, d.reason_primary, d.reasons, flags, Jsonb(package), case["id"]))
            final = await cur.fetchone()
            await audit(conn, ctx, final, "DECIDED_" + d.decision,
                        reason=package["gate_explanation"], clause_ids=clause_ids,
                        before="PROCESSING", after=new_status, key=case["submission_key"],
                        model_id=result.model_id,
                        details={"reasons": d.reasons, "reason_primary": d.reason_primary, "flags": flags,
                                 "question_source": d.question_source, "gate_notes": d.notes})
            if outbox_row:
                await audit(conn, ctx, final, "OUTBOX_WRITTEN", reason="Phản hồi tự động ghi vào outbox",
                            clause_ids=list(result.output.cites), before=new_status, after=new_status,
                            key=f"auto:{case['id']}", details={"outbox_id": str(outbox_row["id"])})
    return final


async def finalize_paused(ctx: Ctx, case: dict) -> dict:
    package = {"gate_explanation": "Hệ thống đang TẠM DỪNG: không xử lý tự động, không gọi AI. "
                                   "Ca được đưa vào hàng chờ nhân viên DSA.",
               "student_said_unverified": [], "verified_from_policy": [], "reasons": [], "flags": ["PAUSED"],
               "handoff_question": None, "suggested_reply": None}
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """UPDATE cases SET status='PENDING_HUMAN', flags=array_append(flags,'PAUSED'), package=%s,
                          lease_until=NULL, updated_at=now()
                   WHERE id=%s AND status='PROCESSING' RETURNING *""", (Jsonb(package), case["id"]))
            row = await cur.fetchone()
            if row is None:
                return await get_case(conn, case["id"])
            await audit(conn, ctx, row, "QUEUED_WHILE_PAUSED", reason="Công tắc tạm dừng đang bật",
                        before="PROCESSING", after="PENDING_HUMAN", key=row["submission_key"])
    return row


# ----------------------------------------------------------------------------------------------------------
# Hành động của nhân viên DSA (Stop / Override / Trả lời / Hủy)
# ----------------------------------------------------------------------------------------------------------
def _need_reason(reason: str | None) -> str:
    if not reason or len(reason.strip()) < 5:
        raise ServiceError(400, "REASON_REQUIRED", "Bắt buộc nhập lý do (tối thiểu 5 ký tự)")
    return reason.strip()


async def set_paused(ctx: Ctx, on: bool, reason: str | None, actor_name: str | None) -> dict:
    """Stop: bật công tắc tạm dừng toàn hệ thống VÀ hủy các ca đang chạy dở (RECEIVED/PROCESSING) để chúng
    không thể tự ghi outbox sau thời điểm dừng. Ca PENDING_HUMAN giữ nguyên trong hàng chờ nhân viên."""
    reason = _need_reason(reason)
    cancelled: list[str] = []
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO system_flags (key, value, updated_at) VALUES ('paused', %s, now())
                   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
                (Jsonb({"on": on, "reason": reason, "by": actor_name}),))
            await audit(conn, ctx, None, "SYSTEM_PAUSED" if on else "SYSTEM_RESUMED", actor="staff",
                        actor_name=actor_name, reason=reason, details={"on": on})
            if on:
                cur = await conn.execute(
                    """UPDATE cases c SET status='CANCELLED', lease_until=NULL, updated_at=now()
                       FROM (SELECT id, status AS old_status FROM cases
                             WHERE status IN ('RECEIVED','PROCESSING') FOR UPDATE) o
                       WHERE c.id = o.id RETURNING c.*, o.old_status""")
                for row in await cur.fetchall():
                    cancelled.append(str(row["id"]))
                    await audit(conn, ctx, row, "CANCELLED_BY_STOP", actor="staff", actor_name=actor_name,
                                reason=reason, before=row["old_status"], after="CANCELLED")
    return {"paused": on, "cancelled": cancelled}


async def cancel_case(ctx: Ctx, case_id, reason: str | None, actor_name: str | None) -> dict:
    reason = _need_reason(reason)
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM cases WHERE id=%s FOR UPDATE", (case_id,))
            before = await cur.fetchone()
            if before is None:
                raise ServiceError(404, "NOT_FOUND", "Không tìm thấy ca")
            cur = await conn.execute(
                """UPDATE cases SET status='CANCELLED', lease_until=NULL, updated_at=now()
                   WHERE id=%s AND status = ANY(%s) RETURNING *""", (case_id, list(CANCELLABLE)))
            row = await cur.fetchone()
            if row is None:
                raise ServiceError(409, "NOT_CANCELLABLE", f"Ca ở trạng thái {before['status']} không hủy được")
            await audit(conn, ctx, row, "CANCELLED", actor="staff", actor_name=actor_name, reason=reason,
                        before=before["status"], after="CANCELLED")
    return row


async def staff_reply(ctx: Ctx, case_id, body: str, reason: str | None, key: str,
                      actor_name: str | None) -> dict:
    """Nhân viên trả lời ca PENDING_HUMAN/ERROR (thay quyết định của AI) => HUMAN_REPLY trong outbox."""
    reason = _need_reason(reason)
    if not body or not body.strip():
        raise ServiceError(400, "EMPTY_REPLY", "Nội dung trả lời trống")
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM outbox WHERE idempotency_key=%s", (f"human:{key}",))
            if await cur.fetchone():   # replay cùng khóa
                return await get_case(conn, case_id)
            cur = await conn.execute("SELECT * FROM cases WHERE id=%s FOR UPDATE", (case_id,))
            before = await cur.fetchone()
            if before is None:
                raise ServiceError(404, "NOT_FOUND", "Không tìm thấy ca")
            if before["status"] not in ("PENDING_HUMAN", "ERROR"):
                raise ServiceError(409, "NOT_REPLYABLE",
                                   f"Ca ở trạng thái {before['status']}; dùng Override nếu ca đã AUTO_REPLIED")
            cur = await conn.execute(
                """INSERT INTO outbox (id, case_id, kind, version, body, status, idempotency_key)
                   VALUES (%s,%s,'HUMAN_REPLY',1,%s,'SENT',%s) RETURNING id""",
                (uuid.uuid4(), case_id, body.strip(), f"human:{key}"))
            ob = await cur.fetchone()
            cur = await conn.execute(
                """UPDATE cases SET status='HUMAN_REPLIED', lease_until=NULL, updated_at=now()
                   WHERE id=%s AND status=%s RETURNING *""", (case_id, before["status"]))
            row = await cur.fetchone()
            await audit(conn, ctx, row, "STAFF_REPLIED", actor="staff", actor_name=actor_name, reason=reason,
                        before=before["status"], after="HUMAN_REPLIED", key=f"human:{key}",
                        details={"outbox_id": str(ob["id"]), "ai_decision": before["decision"]})
    return row


async def override_auto(ctx: Ctx, case_id, body: str, reason: str | None, key: str,
                        actor_name: str | None) -> dict:
    """Override sau khi AUTO đã ghi outbox: tạo phản hồi ĐÍNH CHÍNH, bản cũ -> SUPERSEDED."""
    reason = _need_reason(reason)
    if not body or not body.strip():
        raise ServiceError(400, "EMPTY_REPLY", "Nội dung đính chính trống")
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM outbox WHERE idempotency_key=%s", (f"correction:{key}",))
            if await cur.fetchone():
                return await get_case(conn, case_id)
            cur = await conn.execute("SELECT * FROM cases WHERE id=%s FOR UPDATE", (case_id,))
            before = await cur.fetchone()
            if before is None:
                raise ServiceError(404, "NOT_FOUND", "Không tìm thấy ca")
            if before["status"] not in ("AUTO_REPLIED", "SUPERSEDED"):
                raise ServiceError(409, "NOT_OVERRIDABLE",
                                   f"Override đính chính chỉ áp dụng cho ca đã trả lời tự động (hiện: {before['status']})")
            cur = await conn.execute(
                "SELECT * FROM outbox WHERE case_id=%s AND status='SENT' ORDER BY created_at DESC LIMIT 1", (case_id,))
            old = await cur.fetchone()
            cur = await conn.execute(
                "SELECT coalesce(max(version),0)+1 AS v FROM outbox WHERE case_id=%s AND kind='CORRECTION'", (case_id,))
            version = (await cur.fetchone())["v"]
            await conn.execute("UPDATE outbox SET status='SUPERSEDED' WHERE case_id=%s AND status='SENT'", (case_id,))
            cur = await conn.execute(
                """INSERT INTO outbox (id, case_id, kind, version, body, status, supersedes_id, idempotency_key)
                   VALUES (%s,%s,'CORRECTION',%s,%s,'SENT',%s,%s) RETURNING id""",
                (uuid.uuid4(), case_id, version, body.strip(), old["id"] if old else None, f"correction:{key}"))
            ob = await cur.fetchone()
            cur = await conn.execute(
                """UPDATE cases SET status='SUPERSEDED', updated_at=now() WHERE id=%s AND status=%s RETURNING *""",
                (case_id, before["status"]))
            row = await cur.fetchone()
            await audit(conn, ctx, row, "OVERRIDE_CORRECTION", actor="staff", actor_name=actor_name, reason=reason,
                        before=before["status"], after="SUPERSEDED", key=f"correction:{key}",
                        details={"new_outbox_id": str(ob["id"]),
                                 "superseded_outbox_id": str(old["id"]) if old else None})
    return row


# ----------------------------------------------------------------------------------------------------------
# Truy vấn
# ----------------------------------------------------------------------------------------------------------
async def case_detail(ctx: Ctx, case_id) -> dict:
    async with ctx.db.connection() as conn:
        case = await get_case(conn, case_id)
        if case is None:
            raise ServiceError(404, "NOT_FOUND", "Không tìm thấy ca")
        cur = await conn.execute("SELECT * FROM outbox WHERE case_id=%s ORDER BY created_at", (case_id,))
        outbox = await cur.fetchall()
        cur = await conn.execute("SELECT * FROM audit_log WHERE case_id=%s ORDER BY id", (case_id,))
        audit_rows = await cur.fetchall()
    return {"case": case, "outbox": outbox, "audit": audit_rows}


def to_json(obj):
    return json.loads(json.dumps(obj, default=str))
