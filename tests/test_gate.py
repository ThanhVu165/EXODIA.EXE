"""Gate xác định: kiểm bằng AgentOutput dựng tay (không gọi LLM). Đây là unit test của code gate,
KHÔNG phải kết quả nghiệp vụ hay Verify."""
import pytest

from app.agent_contract import AgentOutput
from app.gate import IncompleteOutput, decide, question_problem, validate
from app.policy import load_policy

Q_OK = "Nhân viên DSA chuyển yêu cầu này cho giảng viên phụ trách học phần nào để xác định lại kết quả kiểm tra?"


def out(**kw):
    base = dict(intent="hỏi", stated_facts=[], cites=["D4.2.transparency"], policy_gap_ids=[],
                signals=dict(asks_determination=False, depends_on_unknown_fact=False, policy_gap=False,
                             suspect_input=False),
                unknown_facts=[], draft_reply="Theo quy định, cần ghi rõ công cụ AI đã dùng.",
                handoff_question=None, suggested_route="DSA_TU_XU_LY", plain_explanation="x")
    sig = kw.pop("signals", {})
    base["signals"].update(sig)
    base.update(kw)
    return AgentOutput.model_validate(base)


def test_auto_when_no_reason():
    d = decide(out(), [], [])
    assert d.decision == "AUTO" and d.reasons == [] and d.flags == [] and d.reply


@pytest.mark.parametrize("signals,primary", [
    ({"policy_gap": True, "asks_determination": True}, "OUT_OF_POLICY"),
    ({"depends_on_unknown_fact": True, "asks_determination": True}, "UNKNOWN_FACT"),
    ({"asks_determination": True}, "REQUIRES_HUMAN_AUTHORITY"),
    ({"policy_gap": True, "depends_on_unknown_fact": True, "asks_determination": True}, "OUT_OF_POLICY"),
])
def test_reason_precedence_and_all_reasons_kept(signals, primary):
    d = decide(out(signals=signals, handoff_question=Q_OK), [], [])
    assert d.decision == "ESCALATE" and d.reason_primary == primary
    assert len(d.reasons) == sum(signals.values())
    assert d.reply is None


def test_suspect_from_prefilter_blocks_reply_even_if_llm_says_auto():
    d = decide(out(), ["VI_IGNORE_RULES"], [])
    assert d.decision == "ESCALATE" and d.reason_primary == "REQUIRES_HUMAN_AUTHORITY"
    assert d.flags == ["SUSPECT_INPUT"] and d.reply is None
    assert d.handoff_question and question_problem(d.handoff_question) is None and d.question_source == "gate"


def test_suspect_from_llm_signal():
    d = decide(out(signals={"suspect_input": True, "policy_gap": True}, handoff_question=Q_OK), [], [])
    assert d.reason_primary == "REQUIRES_HUMAN_AUTHORITY" and "SUSPECT_INPUT" in d.flags


def test_forbidden_phrase_never_auto():
    d = decide(out(draft_reply="Bài của em ĐÃ DUYỆT."), [], [])
    assert d.decision == "ESCALATE" and "FORBIDDEN_PHRASE" in d.flags


def test_incomplete_output_is_error_not_auto():
    with pytest.raises(IncompleteOutput):
        decide(out(cites=[]), [], [])
    with pytest.raises(IncompleteOutput):
        decide(out(draft_reply=""), [], [])


def test_invalid_question_gets_specific_gate_question():
    d = decide(out(signals={"asks_determination": True}, handoff_question="Vui lòng xem xét lại?"), [],
               ["handoff_question chung chung"])
    assert d.decision == "ESCALATE" and "HANDOFF_QUESTION_INVALID" in d.flags
    assert question_problem(d.handoff_question) is None


def test_validate_rejects_unknown_codes():
    p = load_policy()
    code_err, _ = validate(out(cites=["D99"], policy_gap_ids=["D4.1"]), p)
    assert len(code_err) == 2


@pytest.mark.parametrize("q,ok", [
    (None, False), ("Ngắn?", False), ("Một câu hỏi đủ dài nhưng không có dấu hỏi ở cuối câu này.", False),
    ("Vui lòng xem xét hồ sơ của sinh viên này giúp chúng tôi được không ạ?", False), (Q_OK, True)])
def test_question_rules(q, ok):
    assert (question_problem(q) is None) == ok
