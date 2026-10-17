"""Tiền lọc XÁC ĐỊNH phát hiện mẫu prompt-injection trong email (Mục 6.1, gate bước 1).

Nguyên tắc tránh bắt nhầm:
- Mẫu chỉ khớp khi có ĐỐI TƯỢNG là chỉ dẫn/quy định/hệ thống (ví dụ "bỏ qua mọi quy định trước đó"),
  không khớp các cụm đời thường như "xin bỏ qua lỗi trình bày", "xin bỏ qua việc này".
- Yêu cầu ngoại lệ hợp lệ cho một nhận định cụ thể KHÔNG phải injection (do agent/gate xử lý theo lý do).
- So khớp trên văn bản đã chuẩn hóa NFC, chữ thường, và trên bản bỏ dấu (bắt "bo qua moi quy dinh").

Mỗi mẫu có mã để ghi vào audit.
"""
from __future__ import annotations

import re
import unicodedata

_OBJ_VI = r"(?:quy định|quy chế|hướng dẫn|chỉ dẫn|chỉ thị|lệnh|luật lệ|nguyên tắc)"
_OBJ_EN = r"(?:instructions?|rules?|prompts?|guidelines?|policies|policy|directives?)"

PATTERNS: list[tuple[str, str]] = [
    # bỏ qua / phớt lờ chỉ dẫn, có lượng từ hoặc ngữ cảnh "trước đó / ở trên / của hệ thống"
    ("VI_IGNORE_RULES", rf"(?:bỏ qua|phớt lờ|lờ đi|vô hiệu hóa)\s+(?:hết\s+)?(?:mọi|tất cả|toàn bộ)\s+(?:các\s+|những\s+)?{_OBJ_VI}"),
    ("VI_IGNORE_PREVIOUS", rf"(?:bỏ qua|phớt lờ)\s+(?:các\s+|những\s+)?{_OBJ_VI}\s+(?:trước đó|ở trên|phía trên|của hệ thống)"),
    ("EN_IGNORE_RULES", rf"(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier|system|your)\s+{_OBJ_EN}"),
    # chèn chỉ dẫn giả danh hệ thống
    ("SYSTEM_TAG", r"\[\s*(?:hướng dẫn hệ thống|chỉ dẫn hệ thống|system|hệ thống|admin|developer)\s*[:\]]"),
    ("SYSTEM_PROMPT_REF", r"(?:system prompt|chỉ dẫn hệ thống|lời nhắc hệ thống)"),
    ("REVEAL_PROMPT", r"(?:tiết lộ|in ra|hiển thị|cho (?:tôi|em) xem)\s+(?:toàn bộ\s+)?(?:prompt|chỉ dẫn|hướng dẫn|lời nhắc)\s+(?:của\s+)?(?:bạn|hệ thống)"),
    ("EN_REVEAL_PROMPT", r"(?:reveal|print|show|repeat)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)"),
    # đổi vai trò
    ("ROLE_CHANGE_VI", r"(?:từ (?:giờ|bây giờ)|kể từ nay)\s+(?:bạn|hệ thống)\s+(?:là|sẽ là|đóng vai)"),
    ("ROLE_CHANGE_VI2", r"(?:hãy|bạn hãy)\s+đóng vai\s+(?:một\s+)?(?:nhân viên|cán bộ|giảng viên|admin|quản trị)"),
    ("ROLE_CHANGE_EN", r"(?:you are now|pretend to be|developer mode|jailbreak)"),
    # ép trả lời phê duyệt / giả phê duyệt
    ("FORCE_APPROVAL", r"(?:trả lời|ghi|xuất|in)\s+(?:rằng|là|câu)?\s*[\"“'«]?\s*(?:đã duyệt|được miễn|đã phê duyệt|approved)"),
    ("FAKE_APPROVAL", r"(?:đã được|đã)\s+(?:ban|phòng|trưởng phòng|hội đồng|dsa)\s+(?:phê duyệt|duyệt)\s+(?:sẵn|trước)"),
    # giả danh nhân viên
    ("IMPERSONATE_STAFF", r"(?:tôi|mình|em)\s+là\s+(?:cán bộ|nhân viên|chuyên viên|trưởng)\s+(?:của\s+)?(?:ban\s+|phòng\s+)?(?:dsa|chăm sóc người học|công tác sinh viên)"),
]

_COMPILED = [(code, re.compile(p, re.IGNORECASE | re.UNICODE)) for code, p in PATTERNS]


def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().lower()


_COMPILED_ASCII = [(code, re.compile(_strip_accents(p), re.IGNORECASE)) for code, p in PATTERNS]


def detect_injection(email: str) -> list[str]:
    """Trả danh sách mã mẫu khớp (rỗng nếu không nghi ngờ)."""
    text = _norm(email)
    hits = [code for code, rx in _COMPILED if rx.search(text)]
    ascii_text = _strip_accents(text)
    hits += [code for code, rx in _COMPILED_ASCII if rx.search(ascii_text) and code not in hits]
    return hits
