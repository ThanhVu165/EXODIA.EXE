"""Nguồn chính sách DUY NHẤT: policy/QD4002_UEH.md + danh mục mã ground_truth/clause_ids.yaml.

- Phiên bản chính sách = sha256 nội dung policy file (ghi vào mọi dòng audit).
- Đoạn "căn cứ" hiển thị cho nhân viên được CODE trích nguyên văn từ policy file theo mã điều khoản
  (đoạn văn chứa anchor), không do LLM gõ lại.
- Chuẩn hóa (NFC + gộp khoảng trắng) chỉ dùng để so khớp; nội dung trả về là văn bản gốc.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .config import PROJECT_ROOT

CLAUSE_FILE = PROJECT_ROOT / "ground_truth" / "clause_ids.yaml"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


@dataclass(frozen=True)
class Clause:
    id: str
    locator: str
    anchor: str
    is_gap: bool = False
    description: str | None = None


@dataclass(frozen=True)
class Policy:
    text: str
    version: str  # sha256 hex của file
    paragraphs: tuple[str, ...]
    clauses: dict[str, Clause]

    @property
    def short_version(self) -> str:
        return self.version[:12]

    def is_valid_id(self, code: str) -> bool:
        return code in self.clauses

    def paragraph_for(self, code: str) -> str:
        """Đoạn văn nguyên văn trong policy chứa anchor của mã (KeyError nếu mã không tồn tại)."""
        clause = self.clauses[code]
        needle = normalize(clause.anchor)
        for para in self.paragraphs:
            if needle in normalize(para):
                return para
        raise LookupError(f"Anchor của {code} không có trong policy (báo người dùng, không tự sửa)")

    def excerpt(self, code: str) -> dict:
        clause = self.clauses[code]
        return {
            "id": code,
            "locator": clause.locator,
            "is_gap": clause.is_gap,
            "gap_description": clause.description,
            "text": self.paragraph_for(code),
        }


def _paragraphs(text: str) -> tuple[str, ...]:
    paras = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if block:
            paras.append(block.replace("\\.", "."))  # bỏ escape Markdown "1\." khi hiển thị
    return tuple(paras)


@lru_cache(maxsize=1)
def load_policy() -> Policy:
    doc = yaml.safe_load(CLAUSE_FILE.read_text(encoding="utf-8"))
    policy_path = PROJECT_ROOT / doc["policy_file"]
    raw = policy_path.read_bytes()
    text = raw.decode("utf-8")
    clauses: dict[str, Clause] = {}
    for c in doc["clauses"]:
        clauses[c["id"]] = Clause(c["id"], c["locator"], c["anchor"])
    for g in doc["gaps"]:
        clauses[g["id"]] = Clause(g["id"], "Khoảng trống chính sách", g["referenced_anchor"],
                                  is_gap=True, description=g["description"])
    policy = Policy(text=text, version=hashlib.sha256(raw).hexdigest(),
                    paragraphs=_paragraphs(text), clauses=clauses)
    for code in clauses:  # phát hiện sớm: mọi mã phải trích được
        policy.paragraph_for(code)
    return policy
