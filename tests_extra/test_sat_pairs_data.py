"""DO AGENT VIẾT. Kiểm dữ liệu SAT: mã căn cứ hợp lệ, đủ 3 mức trả lời, không chép email dev."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.policy import load_policy, normalize  # noqa: E402


def test_sat_pairs_well_formed():
    data = yaml.safe_load((ROOT / "tests_extra" / "sat_pairs.yaml").read_text(encoding="utf-8"))
    dev = yaml.safe_load((ROOT / "ground_truth" / "cases_dev.yaml").read_text(encoding="utf-8"))
    dev_emails = {normalize(c["email"]) for c in dev["cases"]}
    p = load_policy()
    for it in data["items"]:
        assert all(p.is_valid_id(c) for c in it["cites"])
        assert set(it["answers"]) == {"full", "partial", "offtopic"}
        assert normalize(it["email"]) not in dev_emails
