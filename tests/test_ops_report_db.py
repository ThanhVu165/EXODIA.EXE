"""Báo cáo vận hành trên Postgres THẬT (DB test riêng qua TEST_DATABASE_URL, không phải DB demo).
Dữ liệu ca được chèn trực tiếp với thời điểm trong quá khứ — CHỈ trong DB test."""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from tests_helpers import FixedAgent, make_ctx

from app import ops_report
from app.sla import TZ, SlaConfig

DAY = date(2026, 3, 18)   # thứ Tư; dùng ngày cũ để tách khỏi dữ liệu test khác
CFG = SlaConfig()


def vn(d, hh, mm=0):
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)


async def add_case(conn, *, created, status, source="PUBLIC", reply_at=None, cancel_at=None, flags=(), error=None,
                   staff_at=None, initial=None):
    cid = uuid.uuid4()
    await conn.execute(
        """INSERT INTO cases (id, submission_key, content_hash, email_body, source, status, flags, error_code,
                              created_at, package)
           VALUES (%s,%s,'h','Email giả lập (test báo cáo vận hành)',%s,%s,%s,%s,%s,
                   '{"suggested_route_label": "giảng viên phụ trách/người hướng dẫn"}'::jsonb)""",
        (cid, f"ops-{cid}", source, status, list(flags), error, created))
    async def aud(actor, action, after, at, reason=None):
        await conn.execute("INSERT INTO audit_log (case_id, actor, action, status_after, reason, at) "
                           "VALUES (%s,%s,%s,%s,%s,%s)", (cid, actor, action, after, reason, at))
    await aud("system", "RECEIVED", "RECEIVED", created)
    # trạng thái sau xử lý tự động (trước phản hồi / hủy) — dựng giống các dòng audit thật của service
    mid = created + timedelta(minutes=1)
    first = initial or status
    if first == "ERROR":
        await aud("system", "TECHNICAL_ERROR", "ERROR", mid, f"{error}: chi tiết giả lập")
    elif "PAUSED" in flags:
        await aud("system", "QUEUED_WHILE_PAUSED", "PENDING_HUMAN", mid)
    elif first in ("PENDING_HUMAN", "HUMAN_REPLIED", "CANCELLED"):
        await aud("system", "DECIDED_ESCALATE", "PENDING_HUMAN", mid)
    if reply_at:
        await conn.execute(
            "INSERT INTO outbox (id, case_id, kind, version, body, status, idempotency_key, created_at) "
            "VALUES (%s,%s,'HUMAN_REPLY',1,'trả lời giả lập','SENT',%s,%s)", (uuid.uuid4(), cid, f"h-{cid}", reply_at))
        await aud("staff", "STAFF_REPLIED", "HUMAN_REPLIED", reply_at)
    if cancel_at:
        await aud("staff", "CANCELLED", "CANCELLED", cancel_at)
    if staff_at:
        await conn.execute("INSERT INTO audit_log (case_id, actor, actor_name, action, at) "
                           "VALUES (%s,'staff','NV test','STAFF_NOTE_TEST',%s)", (cid, staff_at))
    return str(cid)


def test_operations_report_semantics(test_db_url):
    async def t():
        ctx = await make_ctx(test_db_url, FixedAgent())
        async with ctx.db.connection() as conn:
            # dọn dữ liệu của chính test này ở các lần chạy trước bằng cách dùng khoảng ngày riêng không được;
            # thay vào đó so sánh theo id các ca vừa tạo.
            ids = {}
            ids["new_open"] = await add_case(conn, created=vn(DAY, 9), status="PENDING_HUMAN")
            ids["new_done"] = await add_case(conn, created=vn(DAY, 9, 30), status="HUMAN_REPLIED",
                                             reply_at=vn(DAY, 11))
            ids["new_cancel"] = await add_case(conn, created=vn(DAY, 10), status="CANCELLED", cancel_at=vn(DAY, 12))
            ids["new_error"] = await add_case(conn, created=vn(DAY, 10, 30), status="ERROR", error="LLM_TIMEOUT")
            # nhận thứ Sáu tuần trước 08:00 -> hạn T4 (DAY) 17:00 -> tại cuối DAY: quá hạn
            ids["old_overdue"] = await add_case(conn, created=vn(DAY - timedelta(days=5), 8), status="PENDING_HUMAN",
                                                flags=["PAUSED"])
            # nhận thứ Hai -> hạn thứ Năm 17:00 -> tại cuối DAY còn < 24h? (T4 24:00 -> T5 17:00 = 17h) -> gần hạn
            ids["old_near"] = await add_case(conn, created=vn(DAY - timedelta(days=2), 8), status="PENDING_HUMAN",
                                             staff_at=vn(DAY, 15))
            # trả lời muộn: nhận 5 ngày trước, trả lời trong DAY sau hạn
            ids["late_done"] = await add_case(conn, created=vn(DAY - timedelta(days=6), 8), status="HUMAN_REPLIED",
                                              reply_at=vn(DAY, 16))
            # bị loại: Verify và demo
            ids["verify"] = await add_case(conn, created=vn(DAY, 9), status="PENDING_HUMAN", source="VERIFY")
            ids["demo"] = await add_case(conn, created=vn(DAY, 9), status="PENDING_HUMAN", source="DEMO_SEED")
        now = vn(DAY + timedelta(days=30), 12)
        rep = await ops_report.operations_report(ctx, DAY, now=now, cfg=CFG)
        open_ids = {i["case_id"]: i for i in rep["open_cases"]}
        mine = set(ids.values())
        assert ids["verify"] not in open_ids and ids["demo"] not in open_ids
        assert ids["new_open"] in open_ids and ids["new_error"] in open_ids            # ERROR không là hoàn tất
        assert ids["new_done"] not in open_ids and ids["new_cancel"] not in open_ids
        assert open_ids[ids["old_overdue"]]["sla_state"] == "OVERDUE"
        assert open_ids[ids["old_overdue"]]["delay"]["cause"].startswith("Ca được nhận khi hệ thống đang tạm dừng")
        assert open_ids[ids["new_error"]]["delay"]["evidence"] == "error_code=LLM_TIMEOUT"
        assert open_ids[ids["old_near"]]["sla_state"] == "NEAR_DUE"
        assert open_ids[ids["old_near"]]["delay"]["cause"] == "Chưa xác định"
        assert open_ids[ids["old_near"]]["last_activity"]["action"] == "STAFF_NOTE_TEST"
        assert open_ids[ids["new_open"]]["delay"]["evidence"] == "chưa có thao tác nào của nhân viên trong audit"
        assert open_ids[ids["new_open"]]["handling_route"].endswith("giảng viên phụ trách/người hướng dẫn")
        # đếm chỉ trên ca của test này (DB test có thể chứa ca khác cùng ngày từ lần chạy trước)
        c = rep["counts"]
        assert c["new"] >= 4 and c["cancelled"] >= 1 and c["completed_reply_flow"] >= 2 and c["completed_late"] >= 1
        rep_demo = await ops_report.operations_report(ctx, DAY, now=now, cfg=CFG, include_demo=True)
        assert ids["demo"] in {i["case_id"] for i in rep_demo["open_cases"]}
        assert ids["verify"] not in {i["case_id"] for i in rep_demo["open_cases"]}
        # trạng thái lịch sử: tại cuối ngày trước DAY, ca new_* chưa tồn tại; old_near còn mở và chưa gần hạn
        prev = await ops_report.operations_report(ctx, DAY - timedelta(days=1), now=now, cfg=CFG)
        prev_ids = {i["case_id"] for i in prev["open_cases"]}
        assert ids["new_open"] not in prev_ids and ids["old_near"] in prev_ids
        assert mine
        await ctx.db.close()
    asyncio.run(t())


def test_future_day_rejected(test_db_url):
    async def t():
        ctx = await make_ctx(test_db_url, FixedAgent())
        try:
            await ops_report.operations_report(ctx, date(2099, 1, 1))
            raise AssertionError("phải lỗi")
        except ValueError:
            pass
        await ctx.db.close()
    asyncio.run(t())


def test_historical_state_rebuilt_from_audit(test_db_url):
    """Tái hiện lỗi người dùng báo: ca ERROR ngày 14, nhân viên trả lời ngày 16.
    Xem lại ngày 14 phải thấy ca còn mở VÀ đang lỗi kỹ thuật (không lấy trạng thái hiện tại HUMAN_REPLIED)."""
    async def t():
        ctx = await make_ctx(test_db_url, FixedAgent())
        d14 = date(2026, 4, 14)   # thứ Ba
        d16 = date(2026, 4, 16)
        async with ctx.db.connection() as conn:
            cid = await add_case(conn, created=vn(d14, 9), status="HUMAN_REPLIED", initial="ERROR",
                                 error="LLM_TIMEOUT", reply_at=vn(d16, 10))
        now = vn(d16 + timedelta(days=10), 12)
        r14 = await ops_report.operations_report(ctx, d14, now=now, cfg=CFG)
        item = {i["case_id"]: i for i in r14["open_cases"]}[cid]
        assert item["status_at_reference"] == "ERROR" and item["current_status"] == "HUMAN_REPLIED"
        assert item["delay"] == {"cause": "Lỗi kỹ thuật khi xử lý tự động", "evidence": "error_code=LLM_TIMEOUT"}
        assert item["handling_route"].startswith("Nhân viên DSA (lỗi kỹ thuật")
        assert r14["counts"]["open_error"] >= 1
        r16 = await ops_report.operations_report(ctx, d16, now=now, cfg=CFG)
        assert cid not in {i["case_id"] for i in r16["open_cases"]}
        await ctx.db.close()
    asyncio.run(t())
