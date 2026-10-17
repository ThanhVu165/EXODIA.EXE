"""Báo cáo vận hành theo ngày — XÁC ĐỊNH, tính bằng code từ cases/outbox/audit_log (không dùng LLM).

Định nghĩa (công bố trên giao diện):
- "Hoàn tất luồng phản hồi (demo)": ca đã có ít nhất một phản hồi ghi vào Outbox (tự động hoặc do nhân viên).
  Đây KHÔNG có nghĩa là vấn đề của sinh viên đã được giải quyết trên thực tế. Không tính: ca chuyển tiếp chưa có phản hồi,
  bản nháp, ca ERROR, xác nhận tiếp nhận.
- "Đã hủy": thống kê riêng, không tính là hoàn tất.
- "Còn mở": chưa hoàn tất và chưa hủy tại thời điểm tham chiếu (cuối ngày báo cáo, hoặc hiện tại nếu là hôm nay).
- Trạng thái, số ca lỗi, tuyến tiếp quản và nguyên nhân chậm được DỰNG LẠI từ audit_log tại thời điểm tham chiếu
  (dòng audit cuối cùng có status_after, at <= tham chiếu); "trạng thái hiện tại" chỉ hiển thị để đối chiếu.
- Dữ liệu Verify/test (source=VERIFY) luôn bị loại. Dữ liệu demo giả lập (source=DEMO_SEED) bị loại trừ khi bật rõ ràng.
- Nguyên nhân chậm chỉ nêu khi có bằng chứng trong dữ liệu; còn lại ghi "Chưa xác định".
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from . import sla
from .service import Ctx, to_json

NEAR_DUE = timedelta(hours=24)
COMPLETION_DEFINITION = ("Hoàn tất luồng phản hồi (demo) = đã có phản hồi ghi vào Outbox; không đồng nghĩa vấn đề "
                         "của sinh viên đã được giải quyết trên thực tế.")


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=sla.TZ)
    return start, start + timedelta(days=1)


def _route(c: dict, status: str | None) -> str:
    """Tuyến tiếp quản theo trạng thái TẠI THỜI ĐIỂM THAM CHIẾU (dựng lại từ audit)."""
    pkg = c.get("package") or {}
    if status is None:
        return "Không xác định được từ audit"
    if status == "ERROR":
        return "Nhân viên DSA (lỗi kỹ thuật — thử lại hoặc trả lời thủ công)"
    if status in ("RECEIVED", "PROCESSING"):
        return "Hệ thống (đang xử lý)"
    if c.get("paused_at_ref"):
        return "Nhân viên DSA (ca nhận khi hệ thống tạm dừng)"
    label = pkg.get("suggested_route_label") if c.get("decided_at_ref") else None
    return f"Nhân viên DSA → gợi ý chuyển: {label}" if label else "Nhân viên DSA"


def _delay(c: dict, status: str | None, ref: datetime, is_live: bool) -> dict:
    """Nguyên nhân chậm chỉ khi có bằng chứng trong audit TẠI hoặc TRƯỚC thời điểm tham chiếu."""
    if status == "ERROR":
        code = (c.get("error_reason_at_ref") or "").split(":", 1)[0] or c.get("error_code")
        return {"cause": "Lỗi kỹ thuật khi xử lý tự động", "evidence": f"error_code={code}"}
    if c.get("paused_at_ref"):
        return {"cause": "Ca được nhận khi hệ thống đang tạm dừng", "evidence": "audit QUEUED_WHILE_PAUSED"}
    # lease chỉ phản ánh hiện tại => chỉ dùng khi báo cáo đang ở thời điểm hiện tại
    if is_live and status == "PROCESSING" and c.get("lease_until") and c["lease_until"] < ref:
        return {"cause": "Kẹt ở bước xử lý (quá thời hạn giữ ca)", "evidence": f"lease_until={c['lease_until'].isoformat()}"}
    facts = []
    if status == "PENDING_HUMAN" and not c.get("staff_actions"):
        facts.append("chưa có thao tác nào của nhân viên trong audit")
    return {"cause": "Chưa xác định", "evidence": "; ".join(facts) or None}


async def operations_report(ctx: Ctx, day: date, include_demo: bool = False, now: datetime | None = None,
                            cfg: sla.SlaConfig | None = None) -> dict:
    cfg = cfg or sla.SlaConfig.from_env()
    now = now or datetime.now(timezone.utc)
    start, end = day_bounds(day)
    if start > now:
        raise ValueError("Ngày báo cáo ở tương lai")
    ref = min(now, end)                      # thời điểm tham chiếu
    is_live = ref == now
    sources = ["PUBLIC", "DEMO_SEED"] if include_demo else ["PUBLIC"]
    async with ctx.db.connection() as conn:
        cur = await conn.execute(
            """
            SELECT c.id, c.status, c.source, c.created_at, c.flags, c.error_code, c.lease_until, c.package,
                   c.decision, c.reason_primary, left(c.email_body, 160) AS email_short,
                   (SELECT min(o.created_at) FROM outbox o WHERE o.case_id = c.id) AS first_reply_at,
                   (SELECT min(a.at) FROM audit_log a WHERE a.case_id = c.id
                       AND a.action IN ('CANCELLED','CANCELLED_BY_STOP')) AS cancelled_at,
                   (SELECT count(*) FROM audit_log a WHERE a.case_id = c.id AND a.actor = 'staff'
                       AND a.at <= %(ref)s) AS staff_actions,
                   la.at AS last_at, la.action AS last_action, la.actor AS last_actor, la.actor_name AS last_actor_name,
                   st.status_after AS status_at_ref,
                   (SELECT a.reason FROM audit_log a WHERE a.case_id = c.id AND a.action = 'TECHNICAL_ERROR'
                       AND a.at <= %(ref)s ORDER BY a.at DESC, a.id DESC LIMIT 1) AS error_reason_at_ref,
                   EXISTS (SELECT 1 FROM audit_log a WHERE a.case_id = c.id AND a.action = 'QUEUED_WHILE_PAUSED'
                       AND a.at <= %(ref)s) AS paused_at_ref,
                   EXISTS (SELECT 1 FROM audit_log a WHERE a.case_id = c.id AND a.action LIKE 'DECIDED_%%'
                       AND a.at <= %(ref)s) AS decided_at_ref
            FROM cases c
            LEFT JOIN LATERAL (SELECT status_after FROM audit_log a
                               WHERE a.case_id = c.id AND a.status_after IS NOT NULL AND a.at <= %(ref)s
                               ORDER BY a.at DESC, a.id DESC LIMIT 1) st ON true
            LEFT JOIN LATERAL (SELECT at, action, actor, actor_name FROM audit_log a
                               WHERE a.case_id = c.id AND a.at <= %(ref)s ORDER BY a.at DESC, a.id DESC LIMIT 1) la ON true
            WHERE c.source = ANY(%(sources)s) AND c.created_at < %(end)s
            ORDER BY c.created_at
            """, {"ref": ref, "end": end, "sources": sources})
        rows = await cur.fetchall()

    def within(ts):
        return ts is not None and start <= ts < end

    new = completed = cancelled = 0
    completed_on_time = completed_late = 0
    open_items = []
    for c in rows:
        due = sla.deadline(c["created_at"], cfg)
        done_at = c["first_reply_at"] if c["first_reply_at"] and c["first_reply_at"] <= ref else None
        cancel_at = c["cancelled_at"] if c["cancelled_at"] and c["cancelled_at"] <= ref else None
        if within(c["created_at"]):
            new += 1
        if within(done_at):
            completed += 1
            if sla.on_time(done_at, due):
                completed_on_time += 1
            else:
                completed_late += 1
        if within(cancel_at):
            cancelled += 1
        if done_at is None and cancel_at is None:
            remaining = due - ref
            state = "OVERDUE" if ref > due else ("NEAR_DUE" if remaining <= NEAR_DUE else "ON_TRACK")
            status_ref = c["status_at_ref"]
            open_items.append({
                "case_id": c["id"], "source": c["source"], "current_status": c["status"],
                "status_at_reference": status_ref,
                "received_at": c["created_at"], "due_at": due, "sla_state": state,
                "hours_remaining": round(remaining.total_seconds() / 3600, 1),
                "decision": c["decision"], "reason_primary": c["reason_primary"], "flags": c["flags"],
                "email_short": c["email_short"],
                "last_activity": {"at": c["last_at"], "action": c["last_action"], "actor": c["last_actor"],
                                  "actor_name": c["last_actor_name"]},
                "handling_route": _route(c, status_ref), "delay": _delay(c, status_ref, ref, is_live),
            })
    order = {"OVERDUE": 0, "NEAR_DUE": 1, "ON_TRACK": 2}
    open_items.sort(key=lambda x: (order[x["sla_state"]], x["due_at"]))
    return to_json({
        "day": day.isoformat(), "timezone": "Asia/Ho_Chi_Minh", "reference_time": ref,
        "generated_at": now, "include_demo": include_demo,
        "sla_note": sla.SLA_NOTE, "completion_definition": COMPLETION_DEFINITION,
        "excluded": "Dữ liệu Verify/test luôn bị loại" + ("" if include_demo else "; dữ liệu demo giả lập bị loại"),
        "counts": {
            "new": new, "completed_reply_flow": completed, "completed_on_time": completed_on_time,
            "completed_late": completed_late, "cancelled": cancelled, "open_at_reference": len(open_items),
            "open_overdue": sum(i["sla_state"] == "OVERDUE" for i in open_items),
            "open_near_due": sum(i["sla_state"] == "NEAR_DUE" for i in open_items),
            "open_error": sum(i["status_at_reference"] == "ERROR" for i in open_items),
            "open_status_unknown": sum(i["status_at_reference"] is None for i in open_items),
        },
        "attention": [i for i in open_items if i["sla_state"] != "ON_TRACK"],
        "open_cases": open_items,
    })
