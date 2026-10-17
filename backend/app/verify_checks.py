"""Kiểm tra XÁC ĐỊNH cho Verify / chạy ca dev — đúng 7 mục ghi ở đầu ground_truth/cases_dev.yaml.

Không dùng LLM làm giám khảo. Không so khớp theo mã ca: mọi kiểm tra đọc từ trường của ca trong YAML.
`reply_should` / `question_should` chỉ hiển thị như checklist duyệt tay, KHÔNG tính điểm.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache

import yaml

from .config import PROJECT_ROOT
from .policy import Policy

CASES_FILE = PROJECT_ROOT / "ground_truth" / "cases_dev.yaml"
# Cờ chỉ mang tính thông tin cho nhân viên (phát hiện trùng nội dung, không chặn) — không tham gia so khớp flags.
INFORMATIONAL_FLAGS = {"NGHI_TRUNG"}


@lru_cache(maxsize=1)
def load_cases() -> dict:
    doc = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    doc["by_id"] = {c["id"]: c for c in doc["cases"]}
    return doc


def _fold(t: str | None) -> str:
    return unicodedata.normalize("NFC", t or "").casefold()


def evaluate(spec: dict, case: dict, outbox: list[dict], policy: Policy, generic_patterns: list[str]) -> dict:
    exp = spec["expected"]
    pkg = case.get("package") or {}
    cites = list(pkg.get("cites") or [])
    actual_flags = [f for f in (case.get("flags") or []) if f not in INFORMATIONAL_FLAGS]
    sent = [o for o in outbox if o.get("kind") == "AUTO_REPLY"]
    reply = sent[0]["body"] if sent else pkg.get("suggested_reply")
    question = pkg.get("handoff_question")
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    if case.get("status") == "ERROR":
        add("0. không lỗi kỹ thuật", False, f"{case.get('error_code')}: {case.get('error_detail')}")
    add("1. decision", case.get("decision") == exp["decision"], f"kỳ vọng {exp['decision']}, thực {case.get('decision')}")
    if exp["decision"] == "ESCALATE":
        add("2. reason_primary", case.get("reason_primary") == exp["reason_primary"],
            f"kỳ vọng {exp['reason_primary']}, thực {case.get('reason_primary')}")
    add("3. flags", sorted(actual_flags) == sorted(exp.get("flags") or []),
        f"kỳ vọng {exp.get('flags') or []}, thực {actual_flags}")
    if exp["decision"] == "AUTO":
        groups = spec.get("must_cite") or []
        missing = [g for g in groups if not any(c in cites for c in g)]
        add("4. must_cite", not missing, f"thiếu nhóm {missing}" if missing else f"cites={cites}")
        bad = [p for p in (spec.get("forbidden_in_reply") or []) if _fold(p) in _fold(reply)]
        add("5. forbidden_in_reply", bool(reply) and not bad,
            f"chứa {bad}" if bad else ("không có phản hồi" if not reply else "không chứa cụm cấm"))
    else:
        q = (question or "").strip()
        probs = []
        if not q:
            probs.append("rỗng")
        else:
            if not q.endswith("?"):
                probs.append("không kết thúc bằng '?'")
            if len(q) < 40:
                probs.append("< 40 ký tự")
            gen = [g for g in generic_patterns if _fold(g) in _fold(q)]
            if gen:
                probs.append(f"chung chung {gen}")
            kws = spec.get("question_keywords_any") or []
            if kws and not any(_fold(k) in _fold(q) for k in kws):
                probs.append(f"không chứa từ khóa nào trong {kws}")
        add("6. handoff_question", not probs, "; ".join(probs) or "đạt")
    unknown = [c for c in cites if not policy.is_valid_id(c)]
    add("7. cites tồn tại", not unknown, f"mã lạ {unknown}" if unknown else "đạt")
    return {
        "case_id": spec["id"],
        "email_short": " ".join(spec["email"].split())[:140],
        "expected": exp,
        "actual": {"status": case.get("status"), "decision": case.get("decision"),
                   "reason_primary": case.get("reason_primary"), "reasons": case.get("reasons"),
                   "flags": case.get("flags"), "cites": cites,
                   "suggested_route": pkg.get("suggested_route"),
                   "error_code": case.get("error_code")},
        "expected_route": spec.get("suggested_route"),
        "question": question,
        "reply": reply,
        "checks": checks,
        "passed": all(c["ok"] for c in checks),
        "manual_checklist": spec.get("reply_should") or spec.get("question_should") or [],
        "system_case_id": str(case.get("id")),
        "usage": case.get("usage"),
    }
