"""Cơ chế bảng kiểm tra điều khiển trên Postgres thật, với FixedAgent CHỈ TRONG TEST.
Chứng minh code kiểm tra đếm đúng; KHÔNG thay cho lần chạy Verify thật với OpenAI."""
import asyncio

from app import verify
from tests_helpers import FixedAgent, make_ctx  # noqa


def test_controls_all_pass_with_auto_agent(test_db_url):
    async def t():
        ctx = await make_ctx(test_db_url, FixedAgent())
        res = await verify.run_controls(ctx)
        assert res["error"] is None, res["error"]
        bad = [r for r in res["results"] if not r["passed"]]
        assert not bad, bad
        assert res["total"] == 8
        runs = await verify.latest_runs(ctx, 1)
        assert runs[0]["id"] == res["run_id"] and runs[0]["status"] == "DONE"
        await ctx.db.close()
    asyncio.run(t())
