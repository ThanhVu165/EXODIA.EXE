"""Lời gọi OpenAI qua Agents SDK.

- Tracing của Agents SDK bị TẮT toàn cục (payload sau này chứa nội dung email sinh viên).
- Model đọc từ OPENAI_MODEL, không hardcode.
- Không có tool nào; max_turns=1.
- Client OpenAI không tự retry (max_retries=0): retry (nếu có) là quyết định có chủ đích ở tầng trên.
"""
from __future__ import annotations

import time

import httpx
from agents import (
    Agent,
    ModelSettings,
    OpenAIResponsesModel,
    RunConfig,
    Runner,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from .agent_contract import AgentOutput
from .config import Settings

set_tracing_disabled(True)

# Lời nhắc chỉ dùng cho smoke test S4 — do agent tự viết, KHÔNG lấy từ ground truth.
SMOKE_INSTRUCTIONS = (
    "Đây là kiểm tra kỹ thuật của hệ thống. Hãy trả về đúng một đối tượng theo schema. "
    "Điền intent='smoke_test', các danh sách để rỗng, mọi signals=false, draft_reply=null, "
    "handoff_question=null, suggested_route='DSA_TU_XU_LY', plain_explanation là một câu tiếng Việt ngắn."
)
SMOKE_INPUT = "Tin nhắn kiểm tra kỹ thuật (synthetic), không phải email sinh viên."


class _ReturnedModelCapture:
    """Ghi lại trường `model` mà API thực sự trả về (không phải model đã yêu cầu)."""

    def __init__(self) -> None:
        self.models: list[str | None] = []

    async def __call__(self, response: httpx.Response) -> None:
        if not response.request.url.path.endswith("/responses"):
            return
        await response.aread()
        try:
            self.models.append(response.json().get("model"))
        except ValueError:
            self.models.append(None)


async def run_smoke_call(settings: Settings) -> dict:
    if not settings.openai_model:
        raise RuntimeError("OPENAI_MODEL chưa đặt")
    capture = _ReturnedModelCapture()
    http = httpx.AsyncClient(
        timeout=settings.llm_timeout_s, event_hooks={"response": [capture]}
    )
    client = AsyncOpenAI(http_client=http, max_retries=0)
    try:
        agent = Agent(
            name="dsa_smoke",
            instructions=SMOKE_INSTRUCTIONS,
            model=OpenAIResponsesModel(settings.openai_model, client),
            model_settings=ModelSettings(max_tokens=settings.llm_max_output_tokens, store=False),
            output_type=AgentOutput,
            tools=[],
        )
        t0 = time.perf_counter()
        result = await Runner.run(
            agent,
            SMOKE_INPUT,
            max_turns=1,
            run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False),
        )
        latency_ms = round((time.perf_counter() - t0) * 1000)
        output = result.final_output
        if not isinstance(output, AgentOutput):
            raise TypeError(f"final_output không phải AgentOutput: {type(output).__name__}")
        usage = result.context_wrapper.usage
        return {
            "requested_model": settings.openai_model,
            "returned_model": capture.models,
            "latency_ms": latency_ms,
            "usage": {
                "requests": usage.requests,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            },
            "parsed_output": output.model_dump(mode="json"),
        }
    finally:
        await http.aclose()
