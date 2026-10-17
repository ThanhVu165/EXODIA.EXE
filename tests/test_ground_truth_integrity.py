"""Hàng rào máy kiểm (Mục 3): file bảo vệ không bị sửa và mọi anchor có trong policy.

Test này CHỈ ĐỌC. Nếu fail: dừng và báo người dùng; không sửa policy/ground_truth/anchor.
"""
import hashlib
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKSUM_FILE = ROOT / "GROUND_TRUTH.sha256"


def _norm(text: str) -> str:
    # Theo clause_ids.yaml: "collapse whitespace; so khớp phân biệt dấu tiếng Việt".
    return re.sub(r"\s+", " ", text).strip()


def _checksum_entries():
    assert CHECKSUM_FILE.is_file(), "Thiếu GROUND_TRUTH.sha256 — DỪNG và báo người dùng"
    entries = []
    # File do người dùng tạo trên Windows dùng CRLF: bỏ '\r' cuối dòng (định dạng dòng, không nới kiểm tra).
    for line in CHECKSUM_FILE.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\r").strip()
        if not line:
            continue
        digest, name = line.split(maxsplit=1)
        entries.append((digest.lower(), name.lstrip("*")))
    assert entries, "GROUND_TRUTH.sha256 rỗng"
    return entries


@pytest.mark.parametrize("digest,name", _checksum_entries())
def test_protected_file_checksum(digest, name):
    path = ROOT / name
    assert path.is_file(), f"Không tìm thấy file bảo vệ: {name} (lưu ý phân biệt hoa/thường trên Linux)"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == digest, f"{name} đã bị sửa: {actual} != {digest}"


def _clause_doc():
    return yaml.safe_load((ROOT / "ground_truth" / "clause_ids.yaml").read_text(encoding="utf-8"))


def test_all_anchors_found_in_policy():
    doc = _clause_doc()
    policy = _norm((ROOT / doc["policy_file"]).read_text(encoding="utf-8"))
    missing = [c["id"] for c in doc["clauses"] if _norm(c["anchor"]) not in policy]
    missing += [g["id"] for g in doc["gaps"] if _norm(g["referenced_anchor"]) not in policy]
    assert not missing, f"Anchor không khớp policy (BÁO CÁO người dùng, không tự sửa): {missing}"


def test_clause_ids_unique():
    doc = _clause_doc()
    ids = [c["id"] for c in doc["clauses"]] + [g["id"] for g in doc["gaps"]]
    assert len(ids) == len(set(ids)), "Trùng mã điều khoản trong clause_ids.yaml"
