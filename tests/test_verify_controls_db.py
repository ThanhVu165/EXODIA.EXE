"""Cơ chế bảng kiểm tra điều khiển trên Postgres thật, với FixedAgent CHỈ TRONG TEST.
Chứng minh code kiểm tra đếm đúng; KHÔNG thay cho lần chạy Verify thật với OpenAI."""
import asyncio

from app import verify
from tests_helpers import FixedAgent, make_ctx  # noqa


def test_controls_all_pass_with_auto_agent(test_db_url):
    async def t():
        ctx = await make_ctx(test_db_url, FixedAgent())
        from app.main import app
        app.state.ctx, app.state.settings, app.state.db = ctx, ctx.settings, ctx.db
        res = await verify.run_controls(ctx, app)
        assert res["error"] is None, res["error"]
        bad = [r for r in res["results"] if not r["passed"]]
        assert not bad, bad
        assert res["total"] == 8
        assert {r["mode"] for r in res["results"]} == {"http", "in-process (lỗi) + http (retry)"}
        runs = await verify.latest_runs(ctx, 1)
        assert runs[0]["id"] == res["run_id"] and runs[0]["status"] == "DONE"
        await ctx.db.close()
    asyncio.run(t())


def test_internal_verify_marker_cannot_come_from_headers(test_db_url):
    """Request từ ngoài (không qua bộ bọc nội bộ) luôn là PUBLIC, kể cả khi gửi header lạ."""
    async def t():
        import uuid
        import httpx
        ctx = await make_ctx(test_db_url, FixedAgent())
        from app.main import app
        app.state.ctx, app.state.settings, app.state.db = ctx, ctx.settings, ctx.db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/emails", json={"body": f"giả lập {uuid.uuid4()}"},
                             headers={"Idempotency-Key": str(uuid.uuid4()),
                                      verify.INTERNAL_SCOPE_KEY: str(uuid.uuid4())})
        assert r.json()["case"]["source"] == "PUBLIC" and r.json()["case"]["verify_run_id"] is None
        await ctx.db.close()
    asyncio.run(t())
