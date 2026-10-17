"""Test xác định cho dịch vụ (idempotency, outbox, audit, stop/override) trên Postgres THẬT.

LƯU Ý: dùng `FixedAgent` — một agent CỐ ĐỊNH chỉ có trong test, để kiểm cơ chế trạng thái/DB một cách
xác định. Đây KHÔNG phải kết quả nghiệp vụ, không dùng cho Verify hay báo cáo 11 ca dev.
"""
import asyncio
import uuid

import pytest

from app import service
from app.agent import AgentTechnicalError
from app.service import ServiceError
from tests_helpers import AUTO_OUT, FixedAgent, make_ctx  # noqa: E402


def run(coro):
    return asyncio.run(coro)


async def count(ctx, sql, *args):
    async with ctx.db.connection() as conn:
        cur = await conn.execute(sql, args)
        return (await cur.fetchone())["n"]


def body(tag=""):
    return f"Email giả lập để kiểm thử {uuid.uuid4()} {tag}"


def test_auto_path_writes_one_outbox_and_full_audit(test_db_url):
    async def t():
        agent = FixedAgent()
        ctx = await make_ctx(test_db_url, agent)
        key = str(uuid.uuid4())
        case, created = await service.process_email(ctx, body=body(), sender=None, key=key)
        assert created and case["status"] == "AUTO_REPLIED" and case["decision"] == "AUTO"
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", case["id"]) == 1
        d = await service.case_detail(ctx, case["id"])
        actions = [a["action"] for a in d["audit"]]
        assert actions == ["RECEIVED", "CLAIMED", "AGENT_CALLED", "DECIDED_AUTO", "OUTBOX_WRITTEN"]
        assert all(a["policy_version"] == ctx.policy.version and a["input_ref"] for a in d["audit"])
        decided = d["audit"][3]
        assert decided["reason"] and decided["clause_ids"] == ["D4.2.transparency"]
        assert decided["status_before"] == "PROCESSING" and decided["status_after"] == "AUTO_REPLIED"
        assert decided["model_id"] == "test-fixed-agent" and decided["idempotency_key"] == key
        # Lớp 1: cùng khóa + cùng nội dung -> trả kết quả cũ, không gọi lại agent
        again, created2 = await service.process_email(ctx, body=case["email_body"], sender=None, key=key)
        assert not created2 and again["id"] == case["id"] and agent.calls == 1
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", case["id"]) == 1
        # cùng khóa + nội dung khác -> 409
        with pytest.raises(ServiceError) as ei:
            await service.process_email(ctx, body="khác hẳn", sender=None, key=key)
        assert ei.value.http_status == 409
        await ctx.db.close()
    run(t())


def test_duplicate_content_new_key_flags_nghi_trung(test_db_url):
    async def t():
        ctx = await make_ctx(test_db_url, FixedAgent())
        b = body()
        c1, _ = await service.process_email(ctx, body=b, sender="sv@example.test", key=str(uuid.uuid4()))
        c2, _ = await service.process_email(ctx, body=b, sender="sv@example.test", key=str(uuid.uuid4()))
        assert c1["id"] != c2["id"] and "NGHI_TRUNG" not in c1["flags"] and "NGHI_TRUNG" in c2["flags"]
        await ctx.db.close()
    run(t())


def test_fault_after_outbox_insert_then_retry_gives_exactly_one_outbox(test_db_url):
    async def t():
        agent = FixedAgent()
        ctx = await make_ctx(test_db_url, agent)
        key, b = str(uuid.uuid4()), body()

        async def boom(point):
            raise RuntimeError(f"lỗi chèn giữa chừng tại {point}")
        case, _ = await service.process_email(ctx, body=b, sender=None, key=key, fault_hook=boom)
        assert case["status"] == "ERROR" and case["error_code"] == "FINALIZE_FAILED"
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", case["id"]) == 0
        case, _ = await service.process_email(ctx, body=b, sender=None, key=key)
        assert case["status"] == "AUTO_REPLIED"
        assert agent.calls == 1  # retry bước thực thi tái dùng đầu ra đã validate
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", case["id"]) == 1
        await ctx.db.close()
    run(t())


def test_concurrent_same_key_processes_once(test_db_url):
    async def t():
        agent = FixedAgent()
        ctx = await make_ctx(test_db_url, agent)
        key, b = str(uuid.uuid4()), body()
        results = await asyncio.gather(*[service.process_email(ctx, body=b, sender=None, key=key) for _ in range(5)],
                                       return_exceptions=True)
        assert not [r for r in results if isinstance(r, Exception)]
        ids = {r[0]["id"] for r in results}
        assert len(ids) == 1 and agent.calls == 1
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", ids.pop()) <= 1
        await ctx.db.close()
    run(t())


def test_pause_queues_without_llm_then_resume(test_db_url):
    async def t():
        agent = FixedAgent()
        ctx = await make_ctx(test_db_url, agent)
        await service.set_paused(ctx, True, "kiểm thử tạm dừng", "pytest")
        case, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        assert case["status"] == "PENDING_HUMAN" and "PAUSED" in case["flags"] and agent.calls == 0
        await service.set_paused(ctx, False, "kết thúc kiểm thử", "pytest")
        case2, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        assert case2["status"] == "AUTO_REPLIED"
        await ctx.db.close()
    run(t())


def test_technical_errors_never_auto(test_db_url):
    async def t():
        ctx = await make_ctx(test_db_url, FixedAgent(error=AgentTechnicalError("LLM_TIMEOUT", "x")))
        case, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        assert case["status"] == "ERROR" and case["error_code"] == "LLM_TIMEOUT"
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", case["id"]) == 0
        await ctx.db.close()
        ctx = await make_ctx(test_db_url, FixedAgent(), llm_daily_cap=0)
        case, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        assert case["status"] == "ERROR" and case["error_code"] == "BUDGET_EXCEEDED"
        await ctx.db.close()
        bad = dict(AUTO_OUT, cites=["D99.khong_co"])
        agent = FixedAgent(outputs=[bad, bad])
        ctx = await make_ctx(test_db_url, agent)
        case, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        assert case["status"] == "ERROR" and case["error_code"] == "INVALID_CLAUSE_CODE" and agent.calls == 2
        await ctx.db.close()
    run(t())


def test_invalid_code_fixed_on_retry(test_db_url):
    async def t():
        agent = FixedAgent(outputs=[dict(AUTO_OUT, cites=["D99"]), AUTO_OUT])
        ctx = await make_ctx(test_db_url, agent)
        case, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        assert case["status"] == "AUTO_REPLIED" and agent.calls == 2
        await ctx.db.close()
    run(t())


def test_cancel_override_and_staff_reply(test_db_url):
    async def t():
        esc = dict(AUTO_OUT, signals=dict(AUTO_OUT["signals"], asks_determination=True), draft_reply=None,
                   handoff_question="Nhân viên DSA chuyển yêu cầu xin ngoại lệ này cho chủ tịch hội đồng trước buổi bảo vệ không?")
        ctx = await make_ctx(test_db_url, FixedAgent(outputs=[esc]))
        c, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        assert c["status"] == "PENDING_HUMAN" and c["reason_primary"] == "REQUIRES_HUMAN_AUTHORITY"
        with pytest.raises(ServiceError):
            await service.cancel_case(ctx, c["id"], "", "pytest")       # thiếu lý do
        c2 = await service.cancel_case(ctx, c["id"], "sinh viên rút yêu cầu", "pytest")
        assert c2["status"] == "CANCELLED"
        with pytest.raises(ServiceError) as ei:
            await service.cancel_case(ctx, c["id"], "hủy lần hai", "pytest")
        assert ei.value.http_status == 409
        # trả lời ca ESCALATE
        c3, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        k = str(uuid.uuid4())
        r = await service.staff_reply(ctx, c3["id"], "Ban đã chuyển cho hội đồng.", "đã liên hệ hội đồng", k, "NV A")
        r2 = await service.staff_reply(ctx, c3["id"], "Ban đã chuyển cho hội đồng.", "đã liên hệ hội đồng", k, "NV A")
        assert r["status"] == r2["status"] == "HUMAN_REPLIED"
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", c3["id"]) == 1
        await ctx.db.close()
        # override ca AUTO
        ctx = await make_ctx(test_db_url, FixedAgent())
        a, _ = await service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4()))
        k = str(uuid.uuid4())
        o = await service.override_auto(ctx, a["id"], "Đính chính: ...", "bổ sung căn cứ", k, "NV B")
        await service.override_auto(ctx, a["id"], "Đính chính: ...", "bổ sung căn cứ", k, "NV B")  # replay
        assert o["status"] == "SUPERSEDED"
        async with ctx.db.connection() as conn:
            cur = await conn.execute("SELECT kind, status, supersedes_id FROM outbox WHERE case_id=%s ORDER BY created_at",
                                     (a["id"],))
            rows = await cur.fetchall()
        assert [(r["kind"], r["status"]) for r in rows] == [("AUTO_REPLY", "SUPERSEDED"), ("CORRECTION", "SENT")]
        assert rows[1]["supersedes_id"] is not None
        d = await service.case_detail(ctx, a["id"])
        ov = [x for x in d["audit"] if x["action"] == "OVERRIDE_CORRECTION"][0]
        assert ov["actor"] == "staff" and ov["reason"] == "bổ sung căn cứ"
        await ctx.db.close()
    run(t())


def test_stop_cancels_in_flight_processing(test_db_url):
    async def t():
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowAgent(FixedAgent):
            async def run(self, email, feedback=None):
                started.set()
                await release.wait()
                return await super().run(email, feedback)
        ctx = await make_ctx(test_db_url, SlowAgent())
        task = asyncio.create_task(service.process_email(ctx, body=body(), sender=None, key=str(uuid.uuid4())))
        await started.wait()
        res = await service.set_paused(ctx, True, "dừng khẩn", "pytest")
        release.set()
        case, _ = await task
        assert str(case["id"]) in res["cancelled"] and case["status"] == "CANCELLED"
        assert await count(ctx, "SELECT count(*) n FROM outbox WHERE case_id=%s", case["id"]) == 0
        await service.set_paused(ctx, False, "mở lại", "pytest")
        await ctx.db.close()
    run(t())
