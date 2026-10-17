"""Gate XÁC ĐỊNH (code) quyết định AUTO/ESCALATE từ đầu ra có cấu trúc của agent (Mục 6.1).

LLM không có quyền duyệt. Mọi trường hợp mơ hồ/thiếu/bất thường => ESCALATE hoặc ERROR, không bao giờ AUTO.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .agent_contract import AgentOutput
from .policy import Policy

REASON_ORDER = ["OUT_OF_POLICY", "UNKNOWN_FACT", "REQUIRES_HUMAN_AUTHORITY"]
REASON_LABEL_VI = {
    "OUT_OF_POLICY": "nằm ngoài phạm vi quy chế / quy chế dẫn chiếu nội dung không có",
    "UNKNOWN_FACT": "chưa xác định được dữ kiện thực tế",
    "REQUIRES_HUMAN_AUTHORITY": "vượt thẩm quyền, cần người có thẩm quyền quyết định",
}
ROUTE_LABEL_VI = {
    "GIANG_VIEN_PHU_TRACH": "giảng viên phụ trách/người hướng dẫn",
    "DON_VI_DAO_TAO": "đơn vị đào tạo/đơn vị quản lý",
    "HOI_DONG_BAO_VE": "hội đồng bảo vệ",
    "BAN_QA_KSNB": "Ban Bảo đảm chất lượng và Kiểm soát nội bộ",
    "BAN_QT_HA_TANG": "Ban Quản trị hạ tầng",
    "DSA_TU_XU_LY": "nhân viên DSA tự xử lý",
}
PREFILTER_LABEL_VI = {
    "VI_IGNORE_RULES": "yêu cầu bỏ qua mọi quy định",
    "VI_IGNORE_PREVIOUS": "yêu cầu bỏ qua quy định trước đó",
    "EN_IGNORE_RULES": "yêu cầu bỏ qua chỉ dẫn (tiếng Anh)",
    "SYSTEM_TAG": "đoạn giả danh chỉ dẫn hệ thống",
    "SYSTEM_PROMPT_REF": "nhắc tới chỉ dẫn hệ thống",
    "REVEAL_PROMPT": "đòi tiết lộ chỉ dẫn hệ thống",
    "EN_REVEAL_PROMPT": "đòi tiết lộ chỉ dẫn hệ thống (tiếng Anh)",
    "ROLE_CHANGE_VI": "yêu cầu hệ thống đổi vai trò",
    "ROLE_CHANGE_VI2": "yêu cầu hệ thống đóng vai nhân viên",
    "ROLE_CHANGE_EN": "yêu cầu đổi vai trò (tiếng Anh)",
    "FORCE_APPROVAL": "ép hệ thống trả lời đã duyệt/được miễn",
    "FAKE_APPROVAL": "tự nhận đã được phê duyệt trước",
    "IMPERSONATE_STAFF": "tự xưng là nhân viên DSA",
}

# Cụm cấm chung trong phản hồi tự động: khẳng định phê duyệt/miễn trừ/kết luận mà hệ thống không có quyền đưa ra.
FORBIDDEN_AUTO_PHRASES = [
    "đã duyệt", "đã được duyệt", "đã phê duyệt", "được miễn", "được phép bỏ qua",
    "chắc chắn không vi phạm", "chắc chắn vi phạm", "chắc chắn không đạo văn",
]
# Mẫu câu hỏi chung chung bị cấm (theo yêu cầu Brief: không dùng "yêu cầu xem xét lại").
GENERIC_QUESTION_PATTERNS = ["vui lòng xem xét", "xin xem xét lại", "hãy xem xét", "kiểm tra lại giúp"]
MIN_QUESTION_LEN = 40


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").casefold()


def question_problem(q: str | None) -> str | None:
    if not q or not q.strip():
        return "thiếu handoff_question"
    q = q.strip()
    if not q.endswith("?"):
        return "handoff_question phải kết thúc bằng '?'"
    if len(q) < MIN_QUESTION_LEN:
        return f"handoff_question quá ngắn (< {MIN_QUESTION_LEN} ký tự)"
    f = _fold(q)
    for pat in GENERIC_QUESTION_PATTERNS:
        if _fold(pat) in f:
            return f"handoff_question chung chung (chứa '{pat}')"
    return None


def forbidden_hits(text: str | None) -> list[str]:
    f = _fold(text or "")
    return [p for p in FORBIDDEN_AUTO_PHRASES if _fold(p) in f]


def any_signal(out: AgentOutput) -> bool:
    s = out.signals
    return s.asks_determination or s.depends_on_unknown_fact or s.policy_gap or s.suspect_input


def validate(out: AgentOutput, policy: Policy) -> tuple[list[str], list[str]]:
    """Trả (lỗi mã điều khoản, lỗi nội dung). Lỗi nào cũng dẫn tới MỘT lần retry có phản hồi lỗi."""
    code_errors = []
    for c in out.cites:
        if not policy.is_valid_id(c) or policy.clauses[c].is_gap:
            code_errors.append(f"mã '{c}' trong cites không có trong danh mục điều khoản")
    for g in out.policy_gap_ids:
        if not policy.is_valid_id(g) or not policy.clauses[g].is_gap:
            code_errors.append(f"mã '{g}' trong policy_gap_ids không phải mã GAP hợp lệ")
    content_errors = []
    if any_signal(out):
        prob = question_problem(out.handoff_question)
        if prob:
            content_errors.append(prob)
    else:
        if not out.cites:
            content_errors.append("không có tín hiệu nào nhưng cites rỗng")
        if not (out.draft_reply or "").strip():
            content_errors.append("không có tín hiệu nào nhưng draft_reply rỗng")
    return code_errors, content_errors


@dataclass
class GateDecision:
    decision: str                        # AUTO | ESCALATE
    reason_primary: str | None
    reasons: list[str]
    flags: list[str]
    reply: str | None                    # chỉ khi AUTO
    handoff_question: str | None
    question_source: str | None          # agent | gate
    notes: list[str] = field(default_factory=list)


def _primary(reasons: list[str]) -> str | None:
    for r in REASON_ORDER:
        if r in reasons:
            return r
    return None


def decide(out: AgentOutput, prefilter_hits: list[str], content_errors_after_retry: list[str]) -> GateDecision:
    """Gọi SAU khi đã validate mã (mã sai sau retry => ERROR ở tầng service, không tới đây)."""
    flags: list[str] = []
    reasons: list[str] = []
    notes: list[str] = []
    s = out.signals
    if s.policy_gap:
        reasons.append("OUT_OF_POLICY")
    if s.depends_on_unknown_fact:
        reasons.append("UNKNOWN_FACT")
    if s.asks_determination:
        reasons.append("REQUIRES_HUMAN_AUTHORITY")

    question = (out.handoff_question or "").strip() or None
    qsource = "agent" if question else None

    # 1. Nghi ngờ injection: luôn ESCALATE, lý do chính REQUIRES_HUMAN_AUTHORITY, chặn draft_reply.
    if prefilter_hits or s.suspect_input:
        flags.append("SUSPECT_INPUT")
        if "REQUIRES_HUMAN_AUTHORITY" not in reasons:
            reasons.append("REQUIRES_HUMAN_AUTHORITY")
        if prefilter_hits:
            notes.append("tiền lọc khớp: " + ", ".join(prefilter_hits))
        if question_problem(question):
            what = "; ".join(PREFILTER_LABEL_VI.get(h, h) for h in prefilter_hits) or "chỉ dẫn nhắm vào hệ thống"
            question = (f"Email chứa nội dung nghi là chỉ dẫn nhắm vào hệ thống ({what}); hệ thống không trả lời "
                        "khẳng định. Nhân viên DSA xác nhận đây có phải yêu cầu hợp lệ của sinh viên không, và nếu có "
                        "thì chuyển cho đơn vị nào có thẩm quyền xử lý?")
            qsource = "gate"
        return GateDecision("ESCALATE", "REQUIRES_HUMAN_AUTHORITY", reasons, flags, None, question, qsource, notes)

    # 2. Có lý do nghiệp vụ => ESCALATE theo thứ tự ưu tiên.
    if reasons:
        if question_problem(question):
            flags.append("HANDOFF_QUESTION_INVALID")
            notes.append("câu hỏi của agent không đạt sau retry: " + "; ".join(content_errors_after_retry))
            route = ROUTE_LABEL_VI.get(out.suggested_route.value, out.suggested_route.value)
            why = "; ".join(REASON_LABEL_VI[r] for r in reasons)
            question = (f"Hệ thống chuyển ca vì {why}, nhưng không tạo được câu hỏi cụ thể. Nhân viên DSA chuyển ca "
                        f"này cho {route} (tuyến gợi ý) hay tự trả lời sinh viên dựa trên các điều khoản đã trích?")
            qsource = "gate"
        return GateDecision("ESCALATE", _primary(reasons), reasons, flags, None, question, qsource, notes)

    # 3. Không có lý do: chỉ AUTO khi đủ mọi điều kiện.
    if content_errors_after_retry or not out.cites or not (out.draft_reply or "").strip():
        raise IncompleteOutput("; ".join(content_errors_after_retry) or "thiếu cites hoặc draft_reply")
    hits = forbidden_hits(out.draft_reply)
    if hits:
        flags.append("FORBIDDEN_PHRASE")
        question = (f"Bản nháp trả lời tự động chứa cụm khẳng định hệ thống không được phép tự gửi "
                    f"({', '.join(hits)}). Nhân viên DSA duyệt gửi nguyên bản nháp, hay sửa lại nội dung trước khi gửi?")
        return GateDecision("ESCALATE", "REQUIRES_HUMAN_AUTHORITY", ["REQUIRES_HUMAN_AUTHORITY"], flags, None,
                            question, "gate", [f"cụm cấm: {hits}"])
    return GateDecision("AUTO", None, [], [], out.draft_reply.strip(), None, None, notes)


class IncompleteOutput(Exception):
    """Đầu ra không đủ điều kiện AUTO và không có lý do nghiệp vụ => ERROR (không AUTO)."""
