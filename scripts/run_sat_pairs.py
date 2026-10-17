#!/usr/bin/env python3
"""SAT-01..03: kiểm Agent 2 THẬT (OpenAI) trên câu trả lời viết sẵn, có nhãn THỨ TỰ do đội đặt.

    python scripts/run_sat_pairs.py --runs 3 --out sat_pairs_result.json

Cần OPENAI_API_KEY và OPENAI_MODEL trong biến môi trường. Không dùng DB, không ghi outbox.
Mỗi lượt = 9 lời gọi Agent 2 (3 câu hỏi × 3 câu trả lời). Đạt khi: full > partial > offtopic ở MỌI lượt.
Đây không phải chứng minh độ chính xác tuyệt đối — chỉ kiểm thứ tự và độ dao động.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import load_settings  # noqa: E402
from app.evaluator import RUBRIC_VERSION, OpenAIEvaluator  # noqa: E402
from app.policy import load_policy  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out")
    a = ap.parse_args()
    data = yaml.safe_load((ROOT / "tests_extra" / "sat_pairs.yaml").read_text(encoding="utf-8"))
    policy, ev = load_policy(), OpenAIEvaluator(load_settings())
    out, all_ok, tokens = [], True, 0
    print(f"Rubric {RUBRIC_VERSION}; nhãn của: {data['label_owner']}")
    for item in data["items"]:
        excerpts = [policy.excerpt(c) for c in item["cites"]]
        scores = {k: [] for k in ("full", "partial", "offtopic")}
        ok_runs = 0
        for r in range(a.runs):
            for k in scores:
                res = await ev.run(item["email"], item["answers"][k], excerpts)
                scores[k].append(res.output.score)
                tokens += res.usage.get("total_tokens", 0)
            if scores["full"][-1] > scores["partial"][-1] > scores["offtopic"][-1]:
                ok_runs += 1
        ok = ok_runs == a.runs
        all_ok &= ok
        spread = {k: (min(v), max(v)) for k, v in scores.items()}
        print(f"{item['id']}: {'ĐẠT' if ok else 'KHÔNG ĐẠT'} ({ok_runs}/{a.runs} lượt đúng thứ tự) | "
              + " | ".join(f"{k}={v} (tb {statistics.mean(v):.0f})" for k, v in scores.items()))
        out.append({"id": item["id"], "scores": scores, "spread": spread, "ordered_runs": ok_runs, "passed": ok})
    print(f"\nTổng: {'ĐẠT' if all_ok else 'KHÔNG ĐẠT'}; token {tokens}")
    if a.out:
        Path(a.out).write_text(json.dumps({"rubric": RUBRIC_VERSION, "runs": a.runs, "items": out}, ensure_ascii=False,
                                          indent=2), encoding="utf-8")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
