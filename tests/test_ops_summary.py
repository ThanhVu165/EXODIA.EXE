"""Kiểm tra bằng code cho đầu ra AI tóm tắt (không gọi LLM): bỏ mã ca lạ, cảnh báo số không có trong đầu vào."""
from app.ops_summary import OpsSummary, check_output, compact_input

REPORT = {
    "day": "2026-03-18", "sla_note": "x",
    "counts": {"new": 4, "completed_reply_flow": 2, "open_at_reference": 3, "cancelled": 1},
    "attention": [{"case_id": "aaa", "sla_state": "OVERDUE", "hours_remaining": -7.0, "current_status": "PENDING_HUMAN",
                   "reason_primary": None, "handling_route": "Nhân viên DSA", "delay": {"cause": "Chưa xác định",
                   "evidence": None}, "due_at": "2026-03-18T17:00:00+07:00", "source": "PUBLIC", "email_short": "bí mật"}],
    "open_cases": [{"case_id": "aaa"}, {"case_id": "bbb"}, {"case_id": "ccc"}],
}


def test_compact_input_has_no_email_text():
    p = compact_input(REPORT)
    assert "email_short" not in p["attention"][0]


def test_drop_unknown_case_and_flag_new_numbers():
    out = OpsSummary.model_validate({"summary": "Có 4 ca mới, 3 ca còn mở, ước tính 12 ca sẽ trễ.",
                                     "priorities": [{"case_id": "aaa", "why": "quá hạn"},
                                                    {"case_id": "zzz", "why": "bịa"}]})
    r = check_output(out, REPORT, compact_input(REPORT))
    assert [p["case_id"] for p in r["priorities"]] == ["aaa"] and r["dropped_refs"] == ["zzz"]
    assert r["unverified_numbers"] == ["12"]
