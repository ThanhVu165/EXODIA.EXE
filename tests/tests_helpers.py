"""Helper test: FixedAgent CHỈ dùng trong test (không phải đường nghiệp vụ)."""
import dataclasses

from app.agent import AgentResult
from app.agent_contract import AgentOutput
from app.config import load_settings
from app.db import Database
from app.policy import load_policy
from app import service
from app.service import Ctx

AUTO_OUT = dict(intent="hỏi khai báo", stated_facts=["Sinh viên nói: dùng công cụ X"], cites=["D4.2.transparency"],
                policy_gap_ids=[], signals=dict(asks_determination=False, depends_on_unknown_fact=False,
                                                 policy_gap=False, suspect_input=False),
                unknown_facts=[], draft_reply="Theo quy định, khi dùng AI tạo sinh cần ghi rõ công cụ và mục đích.",
                handoff_question=None, suggested_route="DSA_TU_XU_LY", plain_explanation="Quy chế trả lời được.")


class FixedAgent:
    def __init__(self, outputs=None, error=None):
        self.outputs = outputs or [AUTO_OUT]
        self.error = error
        self.calls = 0

    async def run(self, email, feedback=None):
        self.calls += 1
        if self.error:
            raise self.error
        o = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        return AgentResult(AgentOutput.model_validate(o), "test-fixed-agent", {"total_tokens": 1}, 1)


async def make_ctx(url, agent, **overrides):
    db = Database(url)
    await db.open()
    await db.ensure_schema()
    settings = dataclasses.replace(load_settings(), **overrides)
    ctx = Ctx(db=db, policy=load_policy(), settings=settings, agent=agent)
    async with db.connection() as conn:
        await service.set_paused(ctx, False, "reset test", "pytest")
    return ctx


