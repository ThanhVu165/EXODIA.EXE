"""Điều phối Agent 2 (chấm mức hài lòng DỰ ĐOÁN), báo cáo theo ngày và rà soát của DSA.

Phạm vi chấm: chỉ phản hồi tự động (outbox kind=AUTO_REPLY) của email công khai — kể cả bản về sau bị nhân viên
đính chính (SUPERSEDED), vì sinh viên đã nhận bản đó. Không chấm ca chuyển tiếp, phản hồi do nhân viên viết,
hay dữ liệu Verify. Lỗi không bao giờ thành 0 điểm. Không có hành động tự động nào dựa trên điểm.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date

from psycopg.types.json import Jsonb

from . import budget
from .agent import AgentTechnicalError
from .evaluator import RUBRIC_VERSION, Evaluator
from .service import Ctx, ServiceError, audit, to_json

log = logging.getLogger("dsa.satisfaction")
STUCK_MINUTES = 10
TZ = "Asia/Ho_Chi_Minh"
BUCKETS = [(0, 39), (40, 69), (70, 89), (90, 100)]


def evaluator_of(ctx: Ctx) -> Evaluator | None:
    return getattr(ctx, "evaluator", None)


async def _claim(ctx: Ctx, outbox_id, retry_failed: bool) -> tuple[dict | None, dict | None]:
    """Trả (đánh giá vừa giành được, ngữ cảnh) hoặc (None, None) nếu ngoài phạm vi / đã có / đang chạy."""
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """SELECT o.id AS outbox_id, o.kind, o.body, o.case_id, c.email_body, c.package, c.source, c.status
                   FROM outbox o JOIN cases c ON c.id = o.case_id WHERE o.id = %s""", (outbox_id,))
            row = await cur.fetchone()
            if row is None or row["kind"] != "AUTO_REPLY" or row["source"] != "PUBLIC":
                return None, None
            retry_states = ["EVALUATION_FAILED"] if retry_failed else []
            cur = await conn.execute(
                f"""INSERT INTO satisfaction_evaluations (id, outbox_id, case_id, status, rubric_version)
                    VALUES (%s, %s, %s, 'RUNNING', %s)
                    ON CONFLICT (outbox_id) DO UPDATE
                       SET status='RUNNING', attempts = satisfaction_evaluations.attempts + 1, started_at = now(),
                           error_code = NULL, rubric_version = EXCLUDED.rubric_version
                     WHERE satisfaction_evaluations.status = ANY(%s)
                        OR (satisfaction_evaluations.status = 'RUNNING'
                            AND satisfaction_evaluations.started_at < now() - interval '{STUCK_MINUTES} minutes')
                    RETURNING *""",
                (uuid.uuid4(), outbox_id, row["case_id"], RUBRIC_VERSION, retry_states))
            ev = await cur.fetchone()
            return ev, row


async def _finish(ctx: Ctx, ev: dict, ctxrow: dict, status: str, *, score=None, reason=None, missing=None,
                  error_code=None, model_id=None, usage=None) -> dict:
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """UPDATE satisfaction_evaluations
                      SET status=%s, score=%s, reason=%s, missing_points=%s, error_code=%s, model_id=%s, usage=%s,
                          evaluated_at=now()
                    WHERE id=%s AND status='RUNNING' RETURNING *""",
                (status, score, reason, missing or [], error_code, model_id,
                 Jsonb(usage) if usage is not None else None, ev["id"]))
            done = await cur.fetchone()
            cur = await conn.execute("SELECT * FROM cases WHERE id=%s", (ctxrow["case_id"],))
            case = await cur.fetchone()
            await audit(conn, ctx, case,
                        "SATISFACTION_EVALUATED" if status == "COMPLETED" else "SATISFACTION_EVAL_" + status,
                        reason=(f"Agent 2 dự đoán mức hài lòng {score}/100: {reason}" if status == "COMPLETED"
                                else f"{status}: {error_code or ''} {reason or ''}".strip()),
                        before=case["status"], after=case["status"], model_id=model_id or ctx.settings.openai_model,
                        details={"evaluation_id": str(ev["id"]), "outbox_id": str(ctxrow["outbox_id"]),
                                 "score": score, "rubric_version": RUBRIC_VERSION, "usage": usage})
    return done or ev


async def evaluate_outbox(ctx: Ctx, outbox_id, retry_failed: bool = False) -> dict | None:
    ev, row = await _claim(ctx, outbox_id, retry_failed)
    if ev is None:
        return None
    email, reply = (row["email_body"] or "").strip(), (row["body"] or "").strip()
    pkg = row["package"] or {}
    codes = [c for c in list(pkg.get("cites") or []) + list(pkg.get("policy_gap_ids") or [])
             if ctx.policy.is_valid_id(c)]
    excerpts = [ctx.policy.excerpt(c) for c in dict.fromkeys(codes)]
    if not email or not reply:
        return await _finish(ctx, ev, row, "INSUFFICIENT_CONTEXT", reason="Thiếu email gốc hoặc nội dung phản hồi")
    evaluator = evaluator_of(ctx)
    if evaluator is None:
        return await _finish(ctx, ev, row, "EVALUATION_FAILED", error_code="LLM_NOT_CONFIGURED")
    async with ctx.db.connection() as conn:
        ok = await budget.consume(conn, budget.BUCKET_LLM_EVAL, "day", ctx.settings.eval_daily_cap)
    if not ok:
        return await _finish(ctx, ev, row, "EVALUATION_FAILED", error_code="BUDGET_EXCEEDED",
                             reason=f"Đã chạm trần {ctx.settings.eval_daily_cap} lượt chấm/ngày")
    try:
        res = await evaluator.run(email, reply, excerpts)
    except AgentTechnicalError as exc:
        return await _finish(ctx, ev, row, "EVALUATION_FAILED", error_code=exc.code, reason=exc.detail[:300])
    except Exception as exc:   # lỗi bất ngờ: ghi trạng thái lỗi, không tạo điểm
        log.exception("Agent 2 lỗi bất ngờ")
        return await _finish(ctx, ev, row, "EVALUATION_FAILED", error_code="INTERNAL_ERROR",
                             reason=f"{type(exc).__name__}: {str(exc)[:200]}")
    o = res.output
    if o.insufficient_context:
        return await _finish(ctx, ev, row, "INSUFFICIENT_CONTEXT", reason=o.reason, model_id=res.model_id,
                             usage=res.usage)
    if not isinstance(o.score, int) or not 0 <= o.score <= 100 or not o.reason.strip():
        return await _finish(ctx, ev, row, "EVALUATION_FAILED", error_code="OUTPUT_INVALID",
                             reason=f"score={o.score!r}", model_id=res.model_id, usage=res.usage)
    return await _finish(ctx, ev, row, "COMPLETED", score=o.score, reason=o.reason.strip(),
                         missing=[m for m in o.missing_points if m.strip()], model_id=res.model_id, usage=res.usage)


async def evaluate_case_in_background(ctx: Ctx, case_id) -> None:
    """Gọi bằng BackgroundTasks sau khi phản hồi AUTO đã ghi outbox: không làm sinh viên chờ thêm.
    Nếu tiến trình restart làm mất tác vụ, phản hồi vẫn hiện là 'chưa chấm' và được chấm bù."""
    try:
        async with ctx.db.connection() as conn:
            cur = await conn.execute("SELECT id FROM outbox WHERE case_id=%s AND kind='AUTO_REPLY'", (case_id,))
            row = await cur.fetchone()
        if row:
            await evaluate_outbox(ctx, row["id"])
    except Exception:  # tác vụ nền: chỉ ghi log; phản hồi đã gửi không bị ảnh hưởng
        log.exception("Không chấm được ca %s trong nền; sẽ được chấm bù", case_id)


async def backfill(ctx: Ctx, limit: int = 10, retry_failed: bool = False) -> dict:
    states = ["EVALUATION_FAILED"] if retry_failed else []
    async with ctx.db.connection() as conn:
        cur = await conn.execute(
            f"""SELECT o.id FROM outbox o JOIN cases c ON c.id=o.case_id
                LEFT JOIN satisfaction_evaluations e ON e.outbox_id=o.id
                WHERE o.kind='AUTO_REPLY' AND c.source='PUBLIC'
                  AND (e.id IS NULL OR e.status = ANY(%s)
                       OR (e.status='RUNNING' AND e.started_at < now() - interval '{STUCK_MINUTES} minutes'))
                ORDER BY o.created_at LIMIT %s""", (states, max(1, min(limit, 20))))
        ids = [r["id"] for r in await cur.fetchall()]
    results = []
    for oid in ids:
        ev = await evaluate_outbox(ctx, oid, retry_failed=retry_failed)
        if ev:
            results.append({"outbox_id": str(oid), "status": ev["status"], "score": ev["score"]})
    return {"processed": len(results), "results": results}


async def review(ctx: Ctx, eval_id, verdict: str, comment: str | None, actor_name: str | None) -> dict:
    if verdict not in ("AGREE", "DISAGREE"):
        raise ServiceError(400, "BAD_VERDICT", "verdict phải là AGREE hoặc DISAGREE")
    if not comment or len(comment.strip()) < 5:
        raise ServiceError(400, "COMMENT_REQUIRED", "Bắt buộc nhập nhận xét (tối thiểu 5 ký tự)")
    async with ctx.db.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """UPDATE satisfaction_evaluations SET review_verdict=%s, review_comment=%s, reviewer=%s,
                          reviewed_at=now()
                   WHERE id=%s AND status='COMPLETED' RETURNING *""",
                (verdict, comment.strip(), actor_name, eval_id))
            ev = await cur.fetchone()
            if ev is None:
                raise ServiceError(409, "NOT_REVIEWABLE", "Chỉ rà soát được đánh giá đã hoàn tất (COMPLETED)")
            cur = await conn.execute("SELECT * FROM cases WHERE id=%s", (ev["case_id"],))
            case = await cur.fetchone()
            await audit(conn, ctx, case, "SATISFACTION_REVIEWED", actor="staff", actor_name=actor_name,
                        reason=f"{'Đồng ý' if verdict == 'AGREE' else 'Không đồng ý'} với đánh giá {ev['score']}/100: "
                               f"{comment.strip()}",
                        before=case["status"], after=case["status"],
                        details={"evaluation_id": str(eval_id), "verdict": verdict})
    return ev


async def daily_report(ctx: Ctx, day: date) -> dict:
    """Báo cáo của một ngày (giờ Việt Nam), tính trực tiếp từ dữ liệu — không có số liệu dựng sẵn.
    Mẫu số của điểm trung bình = số đánh giá COMPLETED (không tính lỗi)."""
    thr = ctx.settings.review_threshold
    async with ctx.db.connection() as conn:
        cur = await conn.execute(
            f"""SELECT o.id AS outbox_id, o.case_id, o.status AS outbox_status, o.created_at AS sent_at, o.body,
                       c.email_body, e.id AS evaluation_id, e.status AS eval_status, e.score, e.reason,
                       e.missing_points, e.error_code, e.model_id, e.rubric_version, e.evaluated_at,
                       e.review_verdict, e.review_comment, e.reviewer, e.reviewed_at
                FROM outbox o JOIN cases c ON c.id = o.case_id
                LEFT JOIN satisfaction_evaluations e ON e.outbox_id = o.id
                WHERE o.kind='AUTO_REPLY' AND c.source='PUBLIC'
                  AND o.created_at >= (%s::date)::timestamp AT TIME ZONE '{TZ}'
                  AND o.created_at <  ((%s::date) + 1)::timestamp AT TIME ZONE '{TZ}'
                ORDER BY o.created_at""", (day, day))
        rows = await cur.fetchall()
    done = [r for r in rows if r["eval_status"] == "COMPLETED"]
    scores = [r["score"] for r in done]
    report = {
        "date": day.isoformat(), "timezone": TZ, "label": "Điểm dự đoán bởi AI — không phải khảo sát sinh viên",
        "rubric_version": RUBRIC_VERSION, "review_threshold": thr,
        "review_threshold_note": "Ngưỡng đề xuất để ưu tiên rà soát, chưa được hiệu chỉnh",
        "sent": len(rows),
        "evaluated": len(done),
        "failed": sum(r["eval_status"] == "EVALUATION_FAILED" for r in rows),
        "insufficient_context": sum(r["eval_status"] == "INSUFFICIENT_CONTEXT" for r in rows),
        "running": sum(r["eval_status"] == "RUNNING" for r in rows),
        "not_evaluated": sum(r["eval_status"] is None for r in rows),
        "average_score": round(sum(scores) / len(scores), 1) if scores else None,
        "distribution": [{"range": f"{a}–{b}", "count": sum(a <= s <= b for s in scores)} for a, b in BUCKETS],
        "corrected_by_staff": sum(r["outbox_status"] == "SUPERSEDED" for r in rows),
        "reviewed": {"agree": sum(r["review_verdict"] == "AGREE" for r in rows),
                     "disagree": sum(r["review_verdict"] == "DISAGREE" for r in rows)},
        "needs_review": sorted([r for r in done if r["score"] < thr], key=lambda r: r["score"]),
        "items": rows,
    }
    return to_json(report)
