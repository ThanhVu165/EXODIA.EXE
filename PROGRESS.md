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

## Cập nhật sau Giai đoạn 1 (2026-10-17)

**Do NGƯỜI DÙNG báo cáo, agent KHÔNG tự chạy/chứng kiến** (agent không tới được Supabase): trên máy Windows của người dùng với `.env.local` đã sửa (bỏ ngoặc quanh mật khẩu, thêm `sslmode=require`):
- S3 PASS: ghi và đọc lại bản ghi smoke qua cổng 5432, SSL bật.
- S5 PASS: `/api/health/ready` 200.
- Lưu ý của người dùng: lần kiểm tra dùng event loop tương thích Windows; lệnh Uvicorn mặc định vẫn lỗi. Chưa kiểm OpenAI (S4, S6 thật) và Railway (S1, S8).

**Nguyên nhân gốc lỗi Uvicorn mặc định trên Windows** (đã đọc mã nguồn): `uvicorn/loops/asyncio.py` trả `ProactorEventLoop` trên win32 khi không reload/subprocess; `psycopg/connection_async.py` từ chối `ProactorEventLoop`. Chỉ ảnh hưởng chạy cục bộ trên Windows; Linux/Docker/Railway dùng SelectorEventLoop nên không bị.
Sửa tối thiểu: `backend/app/event_loop.py` (`selector_loop_factory`), dùng qua `--loop app.event_loop:selector_loop_factory` (đã đưa vào `smoke_local.py` và `RUNBOOK.md`). `CMD` của Dockerfile giữ nguyên. Đã chạy lại trên Linux: 21 test pass, smoke_local pass với cờ mới. **Chưa chạy trên Windows** — người dùng cần xác nhận bằng lệnh Uvicorn có cờ `--loop`.

## Kết quả Railway do NGƯỜI DÙNG báo cáo (agent chưa kiểm chứng trực tiếp)

| Mục | Kết quả | Bằng chứng do người dùng báo |
|---|---|---|
| S1 Docker build Railway | PASS | build thành công, deployment SUCCESS (cần đính kèm log build) |
| S2 Giao diện/API | PASS | trang chủ, ping, live, SPA fallback; /api không tồn tại → 404 JSON |
| S3 Supabase | PASS | ghi/đọc đúng; cổng 5432, SSL bật |
| S4 LLM thật | PASS (cần xác nhận) | `gpt-6-luna`, parse đúng AgentOutput, 3,153 s, 583 token. **Cần xác nhận `returned_model`** (smoke_remote in trường này) |
| S5 Readiness | PASS | /api/health/ready 200, frontend và DB OK |
| S6 Live < 1 s khi gọi LLM | **FAIL theo tiêu chí đã ghi** | 4 mẫu, max 1.835 (đơn vị ghi trong báo cáo là "ms", nhưng theo ngữ cảnh có lẽ là 1 835 ms; cần xác nhận đơn vị) so với ngưỡng 1 000 ms |
| S7 Bundle công khai | PASS | quét index + 7 asset; chưa quét image Docker |
| S8 Sau redeploy | PASS | oldest_id giữ nguyên; 5 dòng |

**Trạng thái S6:** FAIL, chưa kết luận event loop bị chặn. Lý do:
- Ngưỡng 1 s đo từ máy người dùng tới Railway, nên bao gồm RTT mạng và proxy, không chỉ thời gian server xử lý.
- 4 mẫu trong ~3,15 s nghĩa là mỗi lần probe trung bình ~0,5–0,7 s, gợi ý đường mạng đã chậm sẵn; chưa có probe nền (idle) để so sánh.
- Mã gọi LLM là async (AsyncOpenAI + httpx async), không có lời gọi đồng bộ trong đường này. Đây là lý giải, chưa phải bằng chứng.
- Không đổi ngưỡng để qua test. Chỉ được chuyển S6 thành PASS khi có số đo phân tách được mạng và blocking.

**Chẩn đoán đề xuất (chưa chạy):**
1. Đo probe nền: 20 lần `/api/health/live` khi không có LLM, từ cùng máy; ghi p50/p95/max.
2. Chạy `smoke_remote.py --llm` 3–5 lần; ghi toàn bộ mẫu live, không chỉ max.
3. Đo blocking phía server: một endpoint probe ghi độ trễ của `asyncio.sleep(0.1)` trong lúc LLM chạy (loop lag). Loop lag < 50 ms khi LLM đang chạy là bằng chứng không bị chặn; loop lag cao mới là blocking thật.
4. Xem log Railway cùng thời điểm để loại trừ cold start hoặc proxy.

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

---

# GIAI ĐOẠN 2 — Nghiệp vụ

**Quyết định của người dùng (2026-10-17):** "bỏ qua, đi tiếp" — S6 được người dùng **cho qua** (waived), KHÔNG phải PASS; rủi ro event loop vẫn ghi nhận ở trên.

Phân chia checkpoint (C, do agent đề xuất vì BUILD_PROMPT không định nghĩa nội dung 2a–2e):
- 2a: schema DB + nguồn chính sách duy nhất (hash, trích nguyên văn theo mã)
- 2b: agent + tiền lọc injection + gate + endpoint xử lý email (+ script chạy 11 ca dev — cần OpenAI)
- 2c: idempotency 3 lớp, audit, tạm dừng / hủy / override / trả lời của nhân viên
- 2d: ngân sách & giới hạn tần suất, giao diện
- 2e: Verify (General, Escalation) + bảng kiểm tra điều khiển

Môi trường agent không gọi được OpenAI và Supabase ⇒ mọi kiểm chứng cần LLM thật là BLOCKED tại đây; test DB chạy trên Postgres 16 cục bộ qua `TEST_DATABASE_URL`.

## 2a — xong
- `backend/app/schema.sql` (cases, outbox, audit_log, usage_counters, system_flags, verify_runs). Ràng buộc: `cases.submission_key` UNIQUE; `outbox` UNIQUE(case_id, kind, version) + UNIQUE(idempotency_key); trigger chặn UPDATE/DELETE trên `audit_log`; DDL chạy dưới advisory lock.
- `backend/app/policy.py`: version = sha256 file policy; `paragraph_for(code)` trích nguyên văn đoạn chứa anchor.
- Pool psycopg: `autocommit=True` + transaction tường minh (phát hiện khi test: không autocommit thì lỗi giữa chừng làm mất INSERT trước đó trong cùng kết nối).
- Bằng chứng: `python -m pytest -q tests` → `27 passed` (gồm 2 test DB thật trên Postgres cục bộ: UNIQUE, append-only, 5 claim đồng thời chỉ 1 thành công).

## 2b + 2c — mã xong; phần cần LLM thật: BLOCKED tại môi trường agent
(2b và 2c được viết cùng nhau vì idempotency/hành động nhân viên nằm trên cùng đường xử lý; ghi chung một commit.)
- `prompts.py` (chỉ dẫn do agent viết, không chứa email ground truth), `prefilter.py` (mẫu injection có mã, bản có dấu + không dấu), `gate.py` (thứ tự lý do, chặn draft khi nghi vấn, cụm cấm, câu hỏi không chung chung), `agent.py` (Agents SDK, max_turns=1, không tool, ánh xạ lỗi kỹ thuật), `service.py` (tiếp nhận, claim nguyên tử có lease, retry một lần khi mã sai, finalize một transaction, tái dùng đầu ra đã validate khi retry bước thực thi, Stop/Hủy/Trả lời/Override), `budget.py` (bộ đếm trong Postgres), `api.py`.
- Quyết định thiết kế (C) đáng chú ý:
  - Khi tạm dừng: KHÔNG gọi LLM; ca vào `PENDING_HUMAN` + `PAUSED`. Bật Stop còn hủy ca đang `RECEIVED/PROCESSING` để chúng không tự ghi outbox sau thời điểm dừng.
  - Mã điều khoản sai sau 1 retry → `ERROR INVALID_CLAUSE_CODE`; không có lý do nhưng thiếu cites/draft → `ERROR AGENT_OUTPUT_INCOMPLETE`; có lý do nhưng câu hỏi không đạt sau retry → vẫn ESCALATE với câu hỏi do gate soạn + cờ `HANDOFF_QUESTION_INVALID`.
  - Phản hồi AUTO được nối chân trang căn cứ do code sinh (mã + vị trí điều khoản) và nhãn bản demo.
  - Cờ `NGHI_TRUNG` chỉ mang tính thông tin, không tham gia so khớp flags khi chấm.
- Bằng chứng: `python -m pytest -q tests tests_extra` → **67 passed** (gate, prefilter gồm 8 email hợp lệ có cụm giống injection, và 9 test dịch vụ trên Postgres thật dùng `FixedAgent` chỉ-trong-test: 1 outbox/ca, replay không gọi lại agent, 409 khi đổi nội dung, NGHI_TRUNG, lỗi chèn giữa chừng → retry đúng 1 outbox, 5 request đồng thời cùng khóa → 1 lần gọi agent, tạm dừng, lỗi kỹ thuật không AUTO, hủy/trả lời/override).
- HTTP thật (server cục bộ, không có OpenAI): `POST /api/emails` → `ERROR LLM_NOT_CONFIGURED`, không outbox; cùng khóa khác nội dung → 409; thiếu khóa → 400.
- **11 ca dev qua OpenAI thật: BLOCKED** (agent không gọi được OpenAI). Người dùng chạy: `python scripts/run_dev_cases.py <URL> --out dev_run.json` và dán kết quả.
