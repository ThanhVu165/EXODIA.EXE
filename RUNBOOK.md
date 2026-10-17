# RUNBOOK — DSA Intelligence

Mọi lệnh từ clone sạch đến khi chạy (cục bộ và Railway), smoke test, Verify, chạy ca dev.

```bash
git clone https://github.com/ThanhVu165/EXODIA.EXE.git && cd EXODIA.EXE
```

## Biến môi trường

| Biến | Bắt buộc | Ghi chú |
|---|---|---|
| `OPENAI_API_KEY` | có | Chỉ đặt trong Railway Variables / `.env.local`. Không commit, không dán vào chat. |
| `OPENAI_MODEL` | có | Dự kiến `gpt-6-luna`; code không hardcode. |
| `DATABASE_URL` | có | Supabase **Session Pooler**, cổng **5432**, `?sslmode=require`. Cổng 6543 bị app từ chối (ready trả 503). |
| `SMOKE_TOKEN` | chỉ khi smoke | Bật `/api/smoke/*`. Bỏ trống/xóa sau khi smoke xong để tắt các endpoint này. |
| `LLM_TIMEOUT_S` | không | Mặc định 60. |
| `LLM_MAX_OUTPUT_TOKENS` | không | Mặc định 6000 (tính cả token suy luận của model reasoning; 2000 đã gây cắt cụt). Trên Railway phải kiểm tra biến này không còn 2000. |
| `MAX_EMAIL_CHARS` | không | Mặc định 4000. |
| `LLM_DAILY_CAP` | không | Trần toàn cục lượt gọi AI/ngày cho email công khai (mặc định 300) — hàng rào chi phí thật. |
| `VERIFY_DAILY_CAP` | không | Hạn mức riêng của Verify (mặc định 60 lượt AI/ngày; một lần bấm đủ 3 nút ≈ 12–20 lượt). |
| `RATE_PER_IP_PER_MIN` | không | Mặc định 6 (lớp phụ; IP có thể giả mạo). |
| `LEASE_SECONDS` | không | Thời hạn giữ ca ở PROCESSING trước khi cho phép tiếp quản (mặc định 180). |
| `PRICE_INPUT_PER_1M`, `PRICE_OUTPUT_PER_1M` | không | Đơn giá để ước tính chi phí Verify; bỏ trống thì chỉ báo token. |
| `PORT` | Railway cấp | Không tự đặt trên Railway. |

## Chạy cục bộ (không Docker)

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
cd frontend && npm ci && npm run build && cd ..
python -m pytest -q tests
# Đặt biến môi trường từ .env.local rồi:
uvicorn app.main:app --app-dir backend --port 8000 --workers 1 --env-file .env.local
# WINDOWS: thêm --loop app.event_loop:selector_loop_factory (psycopg async không chạy trên ProactorEventLoop mặc định của uvicorn).
# Linux/Docker/Railway: không cần.
```

## Smoke test cục bộ

### PowerShell trên Windows

Từ gốc repo, dùng virtualenv hiện có hoặc tạo bằng `python -m venv .venv`. Không ghi đè `.env.local` đã có key:

```powershell
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
# Điền cấu hình trong .env.local; không dán key hay URI có mật khẩu vào chat.
./.venv/Scripts/python.exe -X utf8 -m pip install -r backend/requirements-dev.txt
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
./.venv/Scripts/python.exe -X utf8 -m pytest -q tests tests_extra
./.venv/Scripts/python.exe -X utf8 -m uvicorn app.main:app --app-dir backend --port 8000 --workers 1 --env-file .env.local --loop app.event_loop:selector_loop_factory
```

Mở http://127.0.0.1:8000. `--env-file` nạp cấu hình vào server; các script smoke không tự đọc `.env.local`, cần nạp biến vào môi trường tiến trình chạy script trước. Dùng UTF-8 trên Windows để tránh lỗi đọc requirements có chú thích tiếng Việt.

```bash
python scripts/smoke_local.py                                   # S2, S5, S7 bundle
python scripts/smoke_local.py --database-url "$DATABASE_URL"    # + S3 (Supabase thật nếu URL là pooler.supabase.com)
python scripts/smoke_local.py --llm                              # + S4, S6 thật (cần OPENAI_API_KEY, OPENAI_MODEL)
docker build -t dsa:local . && python scripts/smoke_local.py --image dsa:local   # S1 + S7 image
```

## Deploy Railway (S8)

1. Push đúng commit lên GitHub, giữ lịch sử đầy đủ. Service hiện tại: `EXODIA.EXE`, project `scintillating-embrace`, source `ThanhVu165/EXODIA.EXE@main`, URL https://exodiaexe-production.up.railway.app. Có thể dùng lại service này; không cần tạo thêm project.
2. Variables: `OPENAI_API_KEY`, `OPENAI_MODEL`, `DATABASE_URL`; các trần mới theo `.env.example`: `MAX_EMAIL_CHARS`, `LLM_DAILY_CAP`, `VERIFY_DAILY_CAP`, `RATE_PER_IP_PER_MIN`, `LEASE_SECONDS`. Để hai biến giá trống nếu chưa có đơn giá được xác minh. Chỉ bật `SMOKE_TOKEN` tạm thời khi chạy smoke.
3. Trong Settings của service, đặt và **kiểm tra trực tiếp**: Builder = Dockerfile, path = `Dockerfile`; Serverless/App Sleeping = TẮT; Healthcheck Path = `/api/health/ready`; Replicas = 1; có Public Domain. Không tự đặt `PORT`. Với service không dùng Config as Code, đặt trực tiếp trong Settings; không xem nội dung `railway.json` là bằng chứng cấu hình đã áp dụng. Xem https://docs.railway.com/infrastructure-as-code#migrating-from-config-as-code.
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

## Test

```bash
python -m pytest -q tests tests_extra
# Test DB cần Postgres thật (cục bộ hoặc một DB thử, KHÔNG dùng DB demo đang chạy):
TEST_DATABASE_URL="postgresql://..." python -m pytest -q tests
```
Không đặt `TEST_DATABASE_URL` thì các test DB bị skip (pytest ghi rõ "skipped").

## Chạy 11 ca dev qua đường thật (OpenAI thật)

```bash
python scripts/run_dev_cases.py https://<app>.up.railway.app --out dev_run.json
# hoặc với server cục bộ: python scripts/run_dev_cases.py http://127.0.0.1:8000
```
Mỗi ca mới đang chạy có thể tốn 1–2 lượt AI (tính vào `LLM_DAILY_CAP`), kể cả khi tiền lọc nghi injection: tiền lọc gắn cờ, không tự bỏ qua lời gọi AI. Khi tạm dừng, hệ thống không gọi AI. Dán bảng in ra nguyên trạng vào PROGRESS.md. Script trả exit code 0 khi chạy xong kể cả có ca FAIL: phải đọc từng dòng và trường `passed` trong JSON, không dùng exit code làm kết luận chất lượng.

Nếu gặp `LLM_OUTPUT_INVALID` với `response.incomplete` / `max_output_tokens`, giữ nguyên ca ERROR và audit. Usage của lời gọi lỗi hiện không được lưu vào kết quả ca, nên tổng token trong báo cáo có thể thiếu và không phải hóa đơn đầy đủ. Không đổi kỳ vọng hay chạy lặp đến khi xanh; phân tích nguyên nhân trước khi thay giới hạn hoặc chỉ dẫn.

Giữ giới hạn IP mặc định 6 yêu cầu/phút. Nếu gặp HTTP 429, đó là lỗi giới hạn tần suất, chưa phải kết quả phân loại; giữ lại báo cáo đầu tiên, chờ sang cửa sổ phút mới rồi dùng `--ids Cxx,Cyy --out dev_retry.json` để chạy riêng các ca bị 429. Không thay kỳ vọng hoặc tăng trần chỉ để báo PASS.

## Verify

Mở Live URL → tab **Verify**: "Chạy Verify (4 ca)", "Escalation Verify (5 ca)", "Kiểm tra điều khiển". Hoặc:
```bash
curl -X POST https://<app>/api/verify/general
curl -X POST https://<app>/api/verify/escalation
curl -X POST https://<app>/api/verify/controls
curl https://<app>/api/verify-runs
```
Kết quả mỗi lần chạy lưu ở bảng `verify_runs`. Dữ liệu Verify gắn `source=VERIFY` + `verify_run_id`, không hiện trong hàng chờ thật.

General/Escalation dùng cùng service, agent thật, gate và DB của API. Bảng điều khiển hiện gọi các hàm service trực tiếp; kiểm tra lỗi giữa chừng dùng hook trong tiến trình. Vì vậy kết quả của bảng này không chứng minh các mục đã đi qua HTTP `/api/emails`; sai khác với yêu cầu HTTP trong prompt vẫn cần chủ sản phẩm duyệt.

Chạy ba nút Verify lần lượt, không đồng thời với xử lý email khác: kiểm tra điều khiển bật Stop thật và khôi phục sau khi chạy. Stop hủy ca RECEIVED/PROCESSING, giữ hàng chờ PENDING_HUMAN; email mới trong lúc dừng chuyển vào hàng chờ, không gọi AI. Giao diện nhân viên chưa có đăng nhập, chỉ dùng dữ liệu giả lập trong demo.

## Hold-out và điều kiện bàn giao

Bốn ca hold-out C04/C08/C11/C13 do người dùng tự giữ và tự nhập qua ô "Xử lý email" trên Live URL. Agent không nhận, tìm, đoán hoặc tái tạo nội dung các ca này. Chưa có kết quả do người giữ bộ ca xác nhận thì ghi NOT RUN/CHƯA XÁC MINH.

Không biến test FixedAgent, kiểm tra schema hoặc kết quả local thành bằng chứng phân loại LIVE. Phân biệt PASS/FAIL từng ca, kiểm tra duyệt tay và ngoại lệ đã được người dùng chấp thuận. S6 từng FAIL theo ngưỡng 1.000 ms trên Railway; waived (nếu chủ sản phẩm chấp thuận) không phải PASS.
