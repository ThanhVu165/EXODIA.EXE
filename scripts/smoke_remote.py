#!/usr/bin/env python3
"""Smoke test từ xa cho URL đã deploy (S2, S5-ready, S3, S4, S6, S7-bundle, dữ liệu sau redeploy).

Dùng (Windows/macOS/Linux, chỉ cần Python 3.9+, không cần cài gói):
    set SMOKE_TOKEN=...            (PowerShell: $env:SMOKE_TOKEN="...")
    python scripts/smoke_remote.py https://<app>.up.railway.app
    python scripts/smoke_remote.py <URL> --db --llm
    python scripts/smoke_remote.py <URL> --db --expect-oldest-id <id-lần-trước>   # sau redeploy

SMOKE_TOKEN đọc từ biến môi trường (không truyền qua dòng lệnh để tránh lộ trong history).
Mỗi lần --llm tốn MỘT lời gọi OpenAI thật.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _smokelib import (Report, check_shell, measure_live_during, request,  # noqa: E402
                       scan_bytes_for_secrets)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--db", action="store_true", help="S3: ghi/đọc bảng smoke qua /api/smoke/db")
    ap.add_argument("--llm", action="store_true", help="S4+S6: một lời gọi LLM thật, đo live song song")
    ap.add_argument("--expect-oldest-id", help="S8: id dòng smoke cũ nhất từ lần chạy trước redeploy")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    token = os.environ.get("SMOKE_TOKEN", "")
    hdr = {"X-Smoke-Token": token} if token else {}
    rep = Report()
    print(f"Smoke remote: {base}")

    check_shell(base, rep)

    r = request("GET", base + "/api/health/ready")
    rep.add("S5 /api/health/ready", "PASS" if r.status == 200 else "FAIL", f"{r.status} {r.body[:200]!r}")

    # S7 (phần bundle công khai): tải index.html và mọi file _next được tham chiếu, quét secret.
    idx = request("GET", base + "/").body
    assets = sorted(set(re.findall(rb'(/_next/[^"\'\s>]+\.(?:js|css))', idx)))
    hits = scan_bytes_for_secrets("index.html", idx, [])
    for path in assets:
        hits += scan_bytes_for_secrets(path.decode(), request("GET", base + path.decode()).body, [])
    rep.add("S7 bundle công khai", "PASS" if not hits else "FAIL",
            f"quét index.html + {len(assets)} asset; trúng: {hits or 'không'}")

    if a.db or a.expect_oldest_id:
        if not token:
            rep.add("S3 DB", "BLOCKED", "thiếu biến môi trường SMOKE_TOKEN")
        else:
            r = request("POST", base + "/api/smoke/db", headers=hdr, body=b"")
            if r.status == 200:
                j = r.json()
                db = j["db"]
                ok = db.get("port") == 5432 and j["client_ssl_in_use"] and j["read_back"]["id"] == j["written_id"]
                rep.add("S3 ghi+đọc Supabase", "PASS" if ok else "FAIL",
                        f"host={db.get('host')} port={db.get('port')} ssl={j['client_ssl_in_use']} id={j['written_id']}")
            else:
                rep.add("S3 ghi+đọc Supabase", "FAIL", f"{r.status} {r.body[:300]!r}")
            r = request("GET", base + "/api/smoke/db", headers=hdr)
            if r.status == 200:
                j = r.json()
                print("   trạng thái bảng smoke:", json.dumps(j, ensure_ascii=False))
                if a.expect_oldest_id:
                    ok = j["oldest_id"] == a.expect_oldest_id
                    rep.add("S8 dữ liệu còn sau redeploy", "PASS" if ok else "FAIL",
                            f"oldest_id={j['oldest_id']} kỳ vọng={a.expect_oldest_id} rows={j['row_count']}")
                else:
                    print(f"   -> Ghi lại oldest_id={j['oldest_id']} để chạy lại với --expect-oldest-id sau redeploy")

    if a.llm:
        if not token:
            rep.add("S4 LLM", "BLOCKED", "thiếu biến môi trường SMOKE_TOKEN")
        else:
            def call():
                return request("POST", base + "/api/smoke/llm", headers=hdr, body=b"", timeout=120)
            box, lat = measure_live_during(base, call)
            res = box.get("result")
            if res is not None and res.status == 200:
                j = res.json()
                rep.add("S4 Agents SDK + AgentOutput", "PASS",
                        f"requested={j['requested_model']} returned={j['returned_model']} "
                        f"latency={j['latency_ms']}ms usage={j['usage']}")
                print("   parsed_output:", json.dumps(j["parsed_output"], ensure_ascii=False))
            else:
                body = res.body[:1500] if res is not None else box.get("error")
                rep.add("S4 Agents SDK + AgentOutput", "FAIL", f"{getattr(res, 'status', '-')} {body!r}")
            mx = max(lat) if lat else None
            ok = bool(lat) and mx < 1000
            rep.add("S6 live trong lúc gọi LLM", "PASS" if ok else "FAIL",
                    f"{len(lat)} mẫu, max={mx:.0f}ms, lời gọi LLM={box.get('elapsed_ms', 0):.0f}ms" if lat
                    else "không lấy được mẫu nào (lời gọi kết thúc quá nhanh?)")
    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
