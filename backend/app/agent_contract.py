"""Hợp đồng đầu ra có cấu trúc của agent — đúng Mục 6.1 của BUILD_PROMPT (thiết kế (C)).

Giai đoạn 1 chỉ dùng để chứng minh S4 (schema được model chấp nhận và parse được).
Quyết định AUTO/ESCALATE KHÔNG nằm ở đây; nó thuộc gate xác định (Giai đoạn 2).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class SuggestedRoute(str, Enum):
    GIANG_VIEN_PHU_TRACH = "GIANG_VIEN_PHU_TRACH"
    DON_VI_DAO_TAO = "DON_VI_DAO_TAO"
    HOI_DONG_BAO_VE = "HOI_DONG_BAO_VE"
    BAN_QA_KSNB = "BAN_QA_KSNB"
    BAN_QT_HA_TANG = "BAN_QT_HA_TANG"
    DSA_TU_XU_LY = "DSA_TU_XU_LY"


class Signals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asks_determination: bool
    depends_on_unknown_fact: bool
    policy_gap: bool
    suspect_input: bool


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str
    stated_facts: list[str]
    cites: list[str]
    policy_gap_ids: list[str]
    signals: Signals
    unknown_facts: list[str]
    draft_reply: str | None
    handoff_question: str | None
    suggested_route: SuggestedRoute
    plain_explanation: str
