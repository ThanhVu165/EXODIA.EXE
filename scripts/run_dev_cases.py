#!/usr/bin/env python3
"""Chạy 11 ca dev qua ĐƯỜNG THẬT (HTTP /api/emails của server đang chạy, OpenAI thật) và in bảng kết quả.

    python scripts/run_dev_cases.py http://127.0.0.1:8000          # hoặc URL Railway
    python scripts/run_dev_cases.py <URL> --ids C01,C07 --out dev_run.json

Chấm bằng backend/app/verify_checks.py (7 kiểm tra xác định ở đầu cases_dev.yaml). Mỗi ca tốn 1–2 lượt LLM.
Ca dev được gửi như email công khai với khóa idempotency mới mỗi lần chạy.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from _smokelib import request  # noqa: E402
from app.policy import load_policy  # noqa: E402
from app.verify_checks import evaluate, load_cases  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--ids")
    ap.add_argument("--out")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    doc = load_cases()
    policy = load_policy()
    ids = a.ids.split(",") if a.ids else [c["id"] for c in doc["cases"]]
    started = datetime.now(timezone.utc).isoformat()
    rows, tokens = [], 0
    for cid in ids:
        spec = doc["by_id"][cid]
        t0 = time.perf_counter()
        r = request("POST", base + "/api/emails", headers={"Content-Type": "application/json",
                                                             "Idempotency-Key": str(uuid.uuid4())},
                    body=json.dumps({"body": spec["email"]}).encode(), timeout=180)
        if r.status not in (200, 201):
            rows.append({"case_id": cid, "passed": False, "http": r.status, "error": r.body[:300].decode("utf-8", "replace")})
            print(f"{cid}: HTTP {r.status} {r.body[:200]!r}")
            continue
        case = r.json()["case"]
        d = request("GET", f"{base}/api/cases/{case['id']}").json()
        row = evaluate(spec, d["case"], d["outbox"], policy, doc["generic_question_patterns"])
        row["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        tokens += (case.get("usage") or {}).get("total_tokens", 0)
        rows.append(row)
        fails = [c["check"] for c in row["checks"] if not c["ok"]]
        print(f"{cid}: {'PASS' if row['passed'] else 'FAIL'} | thực={row['actual']['decision']}/"
              f"{row['actual']['reason_primary']} flags={row['actual']['flags']} | kỳ vọng={spec['expected']['decision']}/"
              f"{spec['expected']['reason_primary']} | lỗi: {fails or '-'} | {row['elapsed_ms']}ms", flush=True)
    print(f"\nBắt đầu {started}; xong {datetime.now(timezone.utc).isoformat()}")
    print(f"Đạt {sum(r.get('passed', False) for r in rows)}/{len(rows)}; tổng token {tokens}")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
