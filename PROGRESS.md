# PROGRESS

Cập nhật: 2026-10-17 — **Giai đoạn 1 xong phần agent làm được; DỪNG chờ người dùng duyệt.** Chưa viết nghiệp vụ.

## Kết quả Giai đoạn 1 (Mục 5)

Môi trường chạy: VM cục bộ (Python 3.12.14 qua uv, Node 22.23.2). Postgres dùng để tự kiểm là **Postgres 16.2 cục bộ (pgserver)**, KHÔNG phải Supabase.

| # | Lệnh đã chạy | Đầu ra thật (rút gọn) | Kết quả |
|---|---|---|---|
| S1 | `docker build` (Cloud: `docker pull python:3.12-slim`, `docker build --check .`) | `registry-1.docker.io ... Forbidden` (cả mirror.gcr.io, public.ecr.aws); VM cục bộ không có docker | **BLOCKED** — Dockerfile viết xong, **CHƯA KIỂM CHỨNG** |
| S2 | `python scripts/smoke_local.py ...` (uvicorn thật, 1 worker) | `/` 200 text/html; `/api/ping` 200 JSON; live 200 (1ms); `/hang-cho/ca-khong-co-file` 200 = index.html; `GET /api/khong-ton-tai`, `POST /api/khong/ton-tai` 404 `application/json` | **PASS (cục bộ, không container)** — trong container: chưa kiểm |
| S3 | `/api/smoke/db` với Postgres cục bộ | ghi uuid `627b1b3d-…` và đọc lại đúng | **BLOCKED với Supabase** (proxy chặn DNS/TCP). Đường code ghi/đọc đã chạy được trên Postgres cục bộ (không tính là S3) |
| S4 | — | `api.openai.com` bị proxy trả 403 CONNECT | **BLOCKED**. Đã kiểm cục bộ: `AgentOutputSchema(AgentOutput)` ở strict mode hợp lệ (test). Chưa chứng minh model thật chấp nhận schema |
| S5 | `smoke_local.py` | đủ điều kiện → 200 `{"frontend":"ok","database":"ok"}`; tắt Postgres lúc đang chạy (`pg_ctl stop`) → 503 `AdminShutdown`; thiếu frontend → 503; DB cổng đóng → 503 `PoolTimeout` | **PASS (cục bộ, Postgres cục bộ)** |
| S6 | `smoke_local.py --stall-upstream 6` | upstream **giả** chậm 6.18s qua đúng đường Agents SDK; 30 mẫu `/api/health/live`, max **1ms** | **PASS MÔ PHỎNG** — chưa có số đo với LLM thật (BLOCKED) |
| S7 | `smoke_local.py` (quét `frontend/out`), `grep` cây dự án | 21 file bundle: không trúng `sk-…`, tên biến env, `postgres://`, `pooler.supabase.com`; cây dự án không có secret | **PASS cho bundle**; image: **BLOCKED** (không build được) |
| S8 | — | cần Railway | **CHỜ NGƯỜI DÙNG** (theo `RUNBOOK.md`). Script `smoke_remote.py` đã chạy thử với server cục bộ: bắt được dữ liệu còn sau khi khởi động lại; và **FAIL đúng** tiêu chí S3 khi DB không phải Supabase/SSL/5432 |
| — | `python -m pytest -q tests` | `21 passed` (toàn vẹn ground truth 4 checksum + 43 anchor, khung app, cấm cổng 6543, HEAD, schema strict) | PASS |

## BLOCKED và việc người dùng cần làm
1. Quyết định về tên file Brief (`BRIEF_` vs `Brief_`) — xem `docs/PREFLIGHT.md` ghi chú B. Nếu không sửa, test toàn vẹn sẽ FAIL trên Linux/CI.
2. Cấu hình git (danh tính commit) hoặc cho phép agent commit — repo chưa có commit nào.
3. Deploy Railway theo `RUNBOOK.md`, chạy `scripts/smoke_remote.py ... --db --llm`, redeploy, chạy lại với `--expect-oldest-id`, dán kết quả (S1 qua log build Railway, S3, S4, S6 thật, S8).

## Cắt giảm/đề xuất có chủ đích (C)
- Endpoint `/api/smoke/*` chỉ bật khi đặt `SMOKE_TOKEN`; tắt hẳn (404) khi không đặt.
- `railway.json` khai báo healthcheck/sleep/replica — chưa kiểm chứng Railway đọc đúng; phải xác nhận trong dashboard.
- Client OpenAI đặt `max_retries=0`; retry sẽ là quyết định có chủ đích ở Giai đoạn 2.

## Checkpoint
- [x] Commit "phase1: infra smoke skeleton" (danh tính git đặt cục bộ trong repo theo đồng ý của người dùng; chưa push).
