"""Thư viện dùng chung cho smoke_local.py và smoke_remote.py — chỉ dùng thư viện chuẩn Python."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

SECRET_PATTERNS = [
    re.compile(rb"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(rb"OPENAI_API_KEY"),
    re.compile(rb"DATABASE_URL"),
    re.compile(rb"SMOKE_TOKEN"),
    re.compile(rb"postgres(ql)?://"),
    re.compile(rb"pooler\.supabase\.com"),
]


@dataclass
class Resp:
    status: int
    headers: dict
    body: bytes
    elapsed_ms: float

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def ctype(self) -> str:
        return self.headers.get("content-type", "")


def request(method: str, url: str, headers: dict | None = None, body: bytes | None = None,
            timeout: float = 30) -> Resp:
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return Resp(r.status, {k.lower(): v for k, v in r.headers.items()}, data,
                        (time.perf_counter() - t0) * 1000)
    except urllib.error.HTTPError as e:
        data = e.read()
        return Resp(e.code, {k.lower(): v for k, v in e.headers.items()}, data,
                    (time.perf_counter() - t0) * 1000)


@dataclass
class Report:
    rows: list = field(default_factory=list)

    def add(self, item: str, status: str, evidence: str) -> None:
        self.rows.append((item, status, evidence))
        print(f"[{status:7}] {item}: {evidence}", flush=True)

    def summary(self) -> int:
        print("\n| Mục | Kết quả | Bằng chứng |\n|---|---|---|")
        for item, status, ev in self.rows:
            print(f"| {item} | {status} | {ev.replace('|', '/')} |")
        return 1 if any(s == "FAIL" for _, s, _ in self.rows) else 0


def check_shell(base: str, rep: Report, tag: str = "S2") -> None:
    """S2: /, /api/ping, live, fallback SPA, /api/* 404 JSON."""
    r = request("GET", base + "/")
    ok = r.status == 200 and "text/html" in r.ctype and b"<html" in r.body.lower()
    rep.add(f"{tag} GET /", "PASS" if ok else "FAIL", f"{r.status} {r.ctype} {len(r.body)}B")
    index_body = r.body
    r = request("GET", base + "/api/ping")
    ok = r.status == 200 and "application/json" in r.ctype and r.json().get("ok") is True
    rep.add(f"{tag} GET /api/ping", "PASS" if ok else "FAIL", f"{r.status} {r.body[:80]!r}")
    r = request("GET", base + "/api/health/live")
    rep.add(f"{tag} GET /api/health/live", "PASS" if r.status == 200 else "FAIL",
            f"{r.status} {r.elapsed_ms:.0f}ms {r.body[:60]!r}")
    r = request("GET", base + "/hang-cho/ca-khong-co-file")
    ok = r.status == 200 and r.body == index_body
    rep.add(f"{tag} fallback /hang-cho/ca-khong-co-file -> index.html", "PASS" if ok else "FAIL",
            f"{r.status} body==index:{r.body == index_body}")
    for method, path in (("GET", "/api/khong-ton-tai"), ("POST", "/api/khong/ton-tai")):
        r = request(method, base + path, body=b"" if method == "POST" else None)
        ok = r.status == 404 and "application/json" in r.ctype and r.body != index_body
        rep.add(f"{tag} {method} {path} -> 404 JSON", "PASS" if ok else "FAIL",
                f"{r.status} {r.ctype} {r.body[:60]!r}")


def scan_bytes_for_secrets(name: str, data: bytes, literal_values: list[bytes]) -> list[str]:
    hits = []
    for pat in SECRET_PATTERNS:
        if pat.search(data):
            hits.append(f"{name}: /{pat.pattern.decode()}/")
    for val in literal_values:
        if val and val in data:
            hits.append(f"{name}: <giá trị secret thật>")
    return hits


def measure_live_during(base: str, slow_call, interval: float = 0.2):
    """Chạy slow_call() trong thread, đồng thời đo /api/health/live. Trả (kết quả, danh sách ms)."""
    box: dict = {}

    def worker():
        t0 = time.perf_counter()
        try:
            box["result"] = slow_call()
        except Exception as e:  # ghi nguyên văn
            box["error"] = f"{type(e).__name__}: {e}"
        box["elapsed_ms"] = (time.perf_counter() - t0) * 1000

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    lat = []
    time.sleep(0.3)  # để lời gọi chậm bắt đầu trước
    while t.is_alive():
        r = request("GET", base + "/api/health/live", timeout=10)
        lat.append(r.elapsed_ms if r.status == 200 else float("inf"))
        time.sleep(interval)
    t.join()
    return box, lat
