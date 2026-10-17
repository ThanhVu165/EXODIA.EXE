"""Trích căn cứ bằng code theo mã điều khoản (không do LLM gõ lại)."""
import hashlib
from pathlib import Path

from app.policy import load_policy, normalize

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_hash_of_policy_file():
    p = load_policy()
    assert p.version == hashlib.sha256((ROOT / "policy" / "QD4002_UEH.md").read_bytes()).hexdigest()


def test_every_code_has_verbatim_paragraph():
    p = load_policy()
    for code, clause in p.clauses.items():
        para = p.paragraph_for(code)
        assert normalize(clause.anchor) in normalize(para)
        # đoạn trích phải là văn bản có thật trong policy (sau khi bỏ escape Markdown)
        assert normalize(para) in normalize(p.text.replace("\\.", "."))


def test_gap_codes_marked():
    p = load_policy()
    gaps = {c for c, cl in p.clauses.items() if cl.is_gap}
    assert gaps == {"GAP.PHULUC3", "GAP.COMPLAINT_PROCEDURE", "GAP.TURNITIN_ACCOUNT_PROCEDURE"}
    assert p.excerpt("GAP.PHULUC3")["gap_description"]


def test_unknown_code_rejected():
    p = load_policy()
    assert not p.is_valid_id("D99.x")
