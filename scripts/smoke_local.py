#!/usr/bin/env python3
"""Smoke test cục bộ: khởi động uvicorn thật (1 worker) và kiểm S2, S3*, S5, S6, S7.

Chạy từ gốc dự án, bằng Python đã cài backend/requirements.txt, sau khi build frontend:
    python scripts/smoke_local.py                          # S2, S5 (thiếu frontend), S7 bundle
    python scripts/smoke_local.py --database-url "$DATABASE_URL" [--db-stop-cmd "..."]
    python scripts/smoke_local.py --llm                    # S4+S6 thật (cần OPENAI_API_KEY, OPENAI_MODEL trong env)
    python scripts/smoke_local.py --stall-upstream 6       # S6 MÔ PHỎNG: upstream giả chậm, KHÔNG phải LLM thật
    python scripts/smoke_local.py --image dsa:local        # S7 quét image Docker

* S3 chỉ là "S3 thật" khi --database-url trỏ tới Supabase Session Pooler. Với Postgres cục bộ, kết quả
  được gắn nhãn LOCAL-PG và không chứng minh S3.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import secrets
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _smokelib import (Report, check_shell, measure_live_during, request,  # noqa: E402
                       scan_bytes_for_secrets)

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, py: str, env_extra: dict, label: str):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = {k: v for k, v in os.environ.items()
               if k not in ("DATABASE_URL", "FRONTEND_DIR", "SMOKE_TOKEN")}
        env.update(env_extra)
        env["PORT"] = str(self.port)
        self.log = tempfile.NamedTemporaryFile(prefix=f"smoke_{label}_", suffix=".log", delete=False)
        self.proc = subprocess.Popen(
            [py, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"),
             "--host", "127.0.0.1", "--port", str(self.port), "--workers", "1",
             "--loop", "app.event_loop:selector_loop_factory"],  # cần cho psycopg async trên Windows
            env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if request("GET", self.base + "/api/health/live", timeout=2).status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.3)
        self.stop()
        raise RuntimeError(f"server {label} không khởi động; xem {self.log.name}")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class _Stall(http.server.BaseHTTPRequestHandler):
    delay = 6.0

    def do_POST(self):  # giả một upstream chậm rồi lỗi — chỉ để đo event loop, không phải LLM
        time.sleep(self.delay)
        self.send_response(500)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":{"message":"simulated upstream for S6 (not a real LLM)"}}')

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--frontend-dir", default=str(ROOT / "frontend" / "out"))
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--db-stop-cmd", help="lệnh tắt DB (để kiểm ready 503 khi DB tắt lúc đang chạy)")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--stall-upstream", type=float)
    ap.add_argument("--image")
    a = ap.parse_args()
    rep = Report()
    token = secrets.token_urlsafe(24)
    fe = Path(a.frontend_dir)
    if not (fe / "index.html").is_file():
        print(f"Chưa build frontend: thiếu {fe / 'index.html'} (chạy `npm ci && npm run build` trong frontend/)")
        return 2

    dbu = a.database_url
    is_supabase = bool(dbu) and "pooler.supabase.com" in (urlsplit(dbu).hostname or "")
    db_label = "Supabase" if is_supabase else "LOCAL-PG"

    env = {"FRONTEND_DIR": str(fe), "SMOKE_TOKEN": token}
    if dbu:
        env["DATABASE_URL"] = dbu
    srv = Server(a.python, env, "main")
    try:
        check_shell(srv.base, rep)
        hdr = {"X-Smoke-Token": token}
        if dbu:
            r = request("GET", srv.base + "/api/health/ready")
            rep.add(f"S5 ready khi đủ điều kiện ({db_label})", "PASS" if r.status == 200 else "FAIL",
                    f"{r.status} {r.body[:160]!r}")
            r = request("POST", srv.base + "/api/smoke/db", headers=hdr, body=b"")
            if r.status == 200:
                j = r.json()
                ok = j["read_back"]["id"] == j["written_id"]
                tag = "S3" if is_supabase else "S3-tương-đương (LOCAL-PG, KHÔNG chứng minh S3)"
                if is_supabase:
                    ok = ok and j["db"]["port"] == 5432 and j["client_ssl_in_use"]
                rep.add(tag, "PASS" if ok else "FAIL", json.dumps(j, ensure_ascii=False)[:300])
            else:
                rep.add("S3 ghi+đọc", "FAIL", f"{r.status} {r.body[:300]!r}")
            if a.db_stop_cmd:
                subprocess.run(shlex.split(a.db_stop_cmd), check=False, capture_output=True)
                time.sleep(1)
                r = request("GET", srv.base + "/api/health/ready", timeout=15)
                rep.add("S5 ready khi DB bị tắt lúc đang chạy", "PASS" if r.status == 503 else "FAIL",
                        f"{r.status} {r.body[:160]!r}")
        else:
            r = request("GET", srv.base + "/api/health/ready")
            rep.add("S5 ready khi KHÔNG có DATABASE_URL", "PASS" if r.status == 503 else "FAIL",
                    f"{r.status} {r.body[:160]!r}")

        if a.llm:
            box, lat = measure_live_during(
                srv.base, lambda: request("POST", srv.base + "/api/smoke/llm", headers=hdr, body=b"", timeout=120))
            res = box.get("result")
            rep.add("S4 LLM thật", "PASS" if res is not None and res.status == 200 else "FAIL",
                    (res.body[:600].decode("utf-8", "replace") if res is not None else box.get("error")))
            rep.add("S6 live < 1s trong lúc gọi LLM thật", "PASS" if lat and max(lat) < 1000 else "FAIL",
                    f"{len(lat)} mẫu, max={max(lat) if lat else float('nan'):.0f}ms")
    finally:
        srv.stop()

    # S5: thiếu frontend
    empty = tempfile.mkdtemp(prefix="no_frontend_")
    env_nf = {"FRONTEND_DIR": empty}
    if dbu:
        env_nf["DATABASE_URL"] = dbu
    s2 = Server(a.python, env_nf, "nofrontend")
    try:
        r = request("GET", s2.base + "/api/health/ready")
        ok = r.status == 503 and r.json()["checks"]["frontend"] != "ok"
        rep.add("S5 ready khi thiếu thư mục frontend", "PASS" if ok else "FAIL", f"{r.status} {r.body[:160]!r}")
    finally:
        s2.stop()

    # S5: DB không kết nối được (cổng đóng)
    s3 = Server(a.python, {"FRONTEND_DIR": str(fe),
                           "DATABASE_URL": f"postgresql://u:p@127.0.0.1:{free_port()}/x?sslmode=disable"}, "dbdown")
    try:
        r = request("GET", s3.base + "/api/health/ready", timeout=15)
        rep.add("S5 ready khi DB không tới được", "PASS" if r.status == 503 else "FAIL", f"{r.status} {r.body[:160]!r}")
    finally:
        s3.stop()

    # S6 mô phỏng
    if a.stall_upstream:
        _Stall.delay = a.stall_upstream
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stall)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        s4 = Server(a.python, {"FRONTEND_DIR": str(fe), "SMOKE_TOKEN": token,
                               "OPENAI_BASE_URL": f"http://127.0.0.1:{httpd.server_port}/v1",
                               "OPENAI_API_KEY": "simulated-not-a-key", "OPENAI_MODEL": "simulated-stall"},
                    "stall")
        try:
            box, lat = measure_live_during(
                s4.base, lambda: request("POST", s4.base + "/api/smoke/llm",
                                         headers={"X-Smoke-Token": token}, body=b"", timeout=60))
            res = box.get("result")
            ok = bool(lat) and max(lat) < 1000
            rep.add("S6 MÔ PHỎNG (upstream giả chậm, KHÔNG phải LLM thật)", "PASS" if ok else "FAIL",
                    f"lời gọi chậm={box.get('elapsed_ms', 0):.0f}ms (kết thúc HTTP {getattr(res, 'status', '-')}), "
                    f"{len(lat)} mẫu live, max={max(lat) if lat else float('nan'):.0f}ms")
        finally:
            s4.stop()
            httpd.shutdown()

    # S7: bundle tĩnh
    literal = [os.environ.get(k, "").encode() for k in ("OPENAI_API_KEY", "SMOKE_TOKEN") if os.environ.get(k)]
    if dbu:
        pw = urlsplit(dbu).password
        if pw:
            literal.append(pw.encode())
    hits, n = [], 0
    for p in fe.rglob("*"):
        if p.is_file():
            n += 1
            hits += scan_bytes_for_secrets(str(p.relative_to(fe)), p.read_bytes(), literal)
    rep.add("S7 bundle tĩnh (frontend/out)", "PASS" if not hits else "FAIL",
            f"quét {n} file; trúng: {hits or 'không'}")

    if a.image:
        inspect = subprocess.run(["docker", "image", "inspect", a.image, "--format", "{{json .Config.Env}}"],
                                 capture_output=True, text=True)
        env_list = json.loads(inspect.stdout or "[]")
        bad_env = [e.split("=", 1)[0] for e in env_list
                   if e.split("=", 1)[0] in ("OPENAI_API_KEY", "DATABASE_URL", "SMOKE_TOKEN")]
        cid = subprocess.run(["docker", "create", a.image], capture_output=True, text=True).stdout.strip()
        tar = subprocess.run(["docker", "export", cid], capture_output=True).stdout
        subprocess.run(["docker", "rm", cid], capture_output=True)
        import io
        import tarfile
        ihits = []
        with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                if m.name.startswith("app/") and (m.name.startswith("app/frontend_out/") or ".env" in m.name):
                    ihits += scan_bytes_for_secrets(m.name, tf.extractfile(m).read(), literal)
                elif literal and m.size < 5_000_000:
                    data = tf.extractfile(m).read()
                    ihits += [f"{m.name}: <giá trị secret thật>" for v in literal if v in data]
        rep.add(f"S7 image {a.image}", "PASS" if not ihits and not bad_env else "FAIL",
                f"ENV chứa secret: {bad_env or 'không'}; trúng: {ihits or 'không'}")
    return rep.summary()


if __name__ == "__main__":
    sys.exit(main())
