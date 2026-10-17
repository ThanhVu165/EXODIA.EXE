# RUNBOOK — DSA Intelligence (bản Giai đoạn 1: hạ tầng)

> Sẽ được bổ sung ở Giai đoạn 3. Hiện chỉ gồm phần cần cho smoke test hạ tầng.

## Biến môi trường

| Biến | Bắt buộc | Ghi chú |
|---|---|---|
| `OPENAI_API_KEY` | có | Chỉ đặt trong Railway Variables / `.env.local`. Không commit, không dán vào chat. |
| `OPENAI_MODEL` | có | Dự kiến `gpt-6-luna`; code không hardcode. |
| `DATABASE_URL` | có | Supabase **Session Pooler**, cổng **5432**, `?sslmode=require`. Cổng 6543 bị app từ chối (ready trả 503). |
| `SMOKE_TOKEN` | chỉ khi smoke | Bật `/api/smoke/*`. Bỏ trống/xóa sau khi smoke xong để tắt các endpoint này. |
| `LLM_TIMEOUT_S` | không | Mặc định 60. |
| `LLM_MAX_OUTPUT_TOKENS` | không | Mặc định 2000. |
| `PORT` | Railway cấp | Không tự đặt trên Railway. |

## Chạy cục bộ (không Docker)

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
cd frontend && npm ci && npm run build && cd ..
python -m pytest -q tests
# Đặt biến môi trường từ .env.local rồi:
uvicorn app.main:app --app-dir backend --port 8000 --workers 1
# WINDOWS: thêm --loop app.event_loop:selector_loop_factory (psycopg async không chạy trên ProactorEventLoop mặc định của uvicorn).
# Linux/Docker/Railway: không cần.
```

## Smoke test cục bộ

```bash
python scripts/smoke_local.py                                   # S2, S5, S7 bundle
python scripts/smoke_local.py --database-url "$DATABASE_URL"    # + S3 (Supabase thật nếu URL là pooler.supabase.com)
python scripts/smoke_local.py --llm                              # + S4, S6 thật (cần OPENAI_API_KEY, OPENAI_MODEL)
docker build -t dsa:local . && python scripts/smoke_local.py --image dsa:local   # S1 + S7 image
```

## Deploy Railway (S8)

1. Tạo project Railway từ repo GitHub (builder Dockerfile; `railway.json` đã khai báo healthcheck `/api/health/ready`, `sleepApplication=false`, 1 replica).
2. Variables: `OPENAI_API_KEY`, `OPENAI_MODEL`, `DATABASE_URL`, `SMOKE_TOKEN` (tạm thời).
3. Trong Settings của service, **tự kiểm tra bằng mắt**: Serverless/App Sleeping = TẮT; Healthcheck Path = `/api/health/ready`; Replicas = 1; đã sinh Public Domain. (Các khóa trong `railway.json` là đề xuất (C) — chưa kiểm chứng Railway nhận đúng, nên phải xác nhận trong dashboard.)
4. Lưu log build (bằng chứng S1 nếu không có Docker cục bộ).
5. Chạy smoke từ xa:
   ```bash
   export SMOKE_TOKEN=...        # PowerShell: $env:SMOKE_TOKEN="..."
   python scripts/smoke_remote.py https://<app>.up.railway.app --db --llm
   ```
   Ghi lại `oldest_id` in ra.
6. Bấm **Redeploy** trên Railway, chờ xong, chạy:
   ```bash
   python scripts/smoke_remote.py https://<app>.up.railway.app --expect-oldest-id <oldest_id>
   ```
7. Dán toàn bộ đầu ra (bảng cuối) cho agent. Sau đó xóa `SMOKE_TOKEN` khỏi Variables nếu không cần nữa.

Ghi chú: app không giới hạn hostname, nên `healthcheck.railway.app` không bị chặn. Healthcheck của Railway chỉ chạy lúc deploy, không giám sát liên tục.
