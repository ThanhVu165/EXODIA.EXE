"""Agent quyết định thật (OpenAI Agents SDK): một agent, không tool, max_turns=1, tracing tắt.

Lỗi kỹ thuật được ánh xạ thành `AgentTechnicalError(code)` — tầng service đưa ca về ERROR, KHÔNG bao giờ AUTO.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import openai
from agents import Agent, ModelSettings, OpenAIResponsesModel, RunConfig, Runner
from agents.exceptions import (AgentsException, MaxTurnsExceeded, ModelBehaviorError,
                               ModelRefusalError, ModelTimeoutError)
from openai import AsyncOpenAI

from .agent_contract import AgentOutput
from .config import Settings
from .llm import _ReturnedModelCapture  # dùng chung bộ ghi model id thực tế trả về; import cũng tắt tracing
from .policy import Policy
from .prompts import build_instructions, wrap_email


class AgentTechnicalError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class AgentResult:
    output: AgentOutput
    model_id: str | None
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0


class AgentRunner(Protocol):
    async def run(self, email: str, feedback: str | None = None) -> AgentResult: ...


class OpenAIAgentRunner:
    def __init__(self, settings: Settings, policy: Policy) -> None:
        if not settings.openai_model:
            raise RuntimeError("OPENAI_MODEL chưa đặt")
        self.settings = settings
        self.instructions = build_instructions(policy)

    async def run(self, email: str, feedback: str | None = None) -> AgentResult:
        capture = _ReturnedModelCapture()
        http = httpx.AsyncClient(timeout=self.settings.llm_timeout_s,
                                 event_hooks={"response": [capture]})
        client = AsyncOpenAI(http_client=http, max_retries=0)
        agent = Agent(
            name="dsa_referee",
            instructions=self.instructions,
            model=OpenAIResponsesModel(self.settings.openai_model, client),
            model_settings=ModelSettings(max_tokens=self.settings.llm_max_output_tokens, store=False),
            output_type=AgentOutput,
            tools=[],
        )
        prompt = wrap_email(email)
        if feedback:
            prompt += ("\n\nLẦN TRẢ LỜI TRƯỚC KHÔNG HỢP LỆ vì: " + feedback +
                       "\nHãy trả lại toàn bộ đối tượng theo schema, đã sửa các lỗi trên.")
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                Runner.run(agent, prompt, max_turns=1,
                           run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)),
                timeout=self.settings.llm_timeout_s + 5,
            )
        except (asyncio.TimeoutError, openai.APITimeoutError, ModelTimeoutError, httpx.TimeoutException) as exc:
            raise AgentTechnicalError("LLM_TIMEOUT", type(exc).__name__) from exc
        except openai.RateLimitError as exc:
            raise AgentTechnicalError("LLM_RATE_LIMIT", str(exc)[:300]) from exc
        except openai.APIStatusError as exc:
            raise AgentTechnicalError("LLM_API_ERROR", f"HTTP {exc.status_code}: {str(exc)[:300]}") from exc
        except openai.APIConnectionError as exc:
            raise AgentTechnicalError("LLM_CONNECTION", type(exc).__name__) from exc
        except (ModelBehaviorError, ModelRefusalError) as exc:
            raise AgentTechnicalError("LLM_OUTPUT_INVALID", str(exc)[:300]) from exc
        except MaxTurnsExceeded as exc:
            raise AgentTechnicalError("LLM_MAX_TURNS", str(exc)[:300]) from exc
        except AgentsException as exc:
            raise AgentTechnicalError("LLM_AGENT_ERROR", f"{type(exc).__name__}: {str(exc)[:300]}") from exc
        finally:
            await http.aclose()
        output = result.final_output
        if not isinstance(output, AgentOutput):
            raise AgentTechnicalError("LLM_OUTPUT_INVALID", f"final_output={type(output).__name__}")
        u = result.context_wrapper.usage
        returned = [m for m in capture.models if m]
        return AgentResult(
            output=output,
            model_id=returned[-1] if returned else None,
            usage={"requests": u.requests, "input_tokens": u.input_tokens,
                   "output_tokens": u.output_tokens, "total_tokens": u.total_tokens},
            latency_ms=round((time.perf_counter() - t0) * 1000),
        )
