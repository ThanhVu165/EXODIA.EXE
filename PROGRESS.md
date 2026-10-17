# PROGRESS

Cập nhật: 2026-10-17 — **Giai đoạn 2–3 đã deploy; kiểm thử LIVE phát hiện lỗi, chưa nghiệm thu.** Kết quả hiện tại ở mục cuối "Kiểm chứng lại bản sửa 0d027bb" (dev 9/11, General 2/4, Escalation 5/5, Controls 8/8). Các mục trước đó là lịch sử theo môi trường/phiên chạy, không phải trạng thái hiện tại.

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

## 2e (backend) — Verify
- `verify_checks.py`: 7 kiểm tra xác định đọc từ `cases_dev.yaml` (không nhánh theo mã ca); `reply_should`/`question_should` chỉ hiển thị.
- `verify.py`: General (4 ca) và Escalation (5 ca) gọi `service.process_email` với `source=VERIFY`, hạn mức `llm:verify`; lưu `verify_runs` (dấu thời gian, id lần chạy, thời lượng, token, chi phí ước tính nếu đặt đơn giá).
- Bảng kiểm tra điều khiển 8 mục. **Lệch so với BUILD_PROMPT (C, cần người dùng duyệt):** các mục chạy qua CÙNG hàm service mà API gọi (mode=service) chứ không gửi HTTP vào chính server, vì giới hạn tần suất theo IP và để dùng hạn mức Verify riêng; mục 4 dùng hook trong tiến trình (mode=in-process). Mục 5 bật/tắt công tắc tạm dừng thật — nếu có người dùng khác đang xử lý đúng lúc đó, ca của họ có thể bị hủy (Stop hủy ca đang chạy dở).
- Bằng chứng cơ chế: test `test_controls_all_pass_with_auto_agent` (FixedAgent chỉ trong test) → 8/8; tổng `68 passed`. Chạy Verify với OpenAI thật: BLOCKED tại đây.

## 2d — ngân sách + giao diện
- Ngân sách (Mục 6.6): email ≤ 4.000 ký tự; giới hạn theo IP/phút (lớp phụ, IP có thể giả mạo); trần toàn cục/ngày `LLM_DAILY_CAP` (mặc định 300) là hàng rào thật; Verify có hạn mức riêng `VERIFY_DAILY_CAP` (60); mọi bộ đếm trong Postgres; vượt trần → `ERROR BUDGET_EXCEEDED`; Verify ghi token và chi phí ước tính (chỉ khi đặt `PRICE_INPUT_PER_1M`/`PRICE_OUTPUT_PER_1M`, agent không tự bịa đơn giá).
- Giao diện một trang (tab theo hash): Xử lý email · Hàng chờ nhân viên DSA · Outbox · Verify · Nhật ký kiểm toán; công tắc Stop toàn cục ở đầu trang; biểu ngữ synthetic; tách "Sinh viên nói (chưa xác minh)" và "Căn cứ quy chế".
- Bằng chứng: `npm run build` OK; tự xem giao diện bằng Chromium headless trong môi trường agent với một agent cố định CHỈ ĐỂ XEM GIAO DIỆN (không nằm trong repo, không phải kết quả nghiệp vụ): luồng ESCALATE, AUTO, bảng kiểm tra điều khiển 8/8, chi tiết ca + audit, màn hình 390px; không có lỗi console. `smoke_local.py` vẫn PASS với khung mới; `pytest` 68 passed.

---

# GIAI ĐOẠN 3 — Bàn giao (phần agent làm được)
- `RUNBOOK.md` (clone → chạy, biến môi trường, test, chạy ca dev, Verify, Railway), `README.md` (biểu ngữ, thật/giả lập), `docs/AI_USAGE.md`, `.env.example` cập nhật.

## Giới hạn và rủi ro đã biết (dữ kiện thô cho Slide 5)
1. **Chưa có kết quả chạy thật với OpenAI** cho 11 ca dev và Verify (môi trường agent bị chặn). Chất lượng phân loại (đặc biệt ranh giới "câu hỏi thông tin" ↔ "xin kết luận", và khi nào đặt `policy_gap`) chưa được đo.
2. S6 (event loop khi gọi LLM) do người dùng cho qua, chưa chứng minh trên Railway.
3. Giao diện nhân viên không có đăng nhập: bất kỳ ai có URL đều có thể Dừng/Hủy/Override (chấp nhận cho demo; mọi thao tác đều ghi audit).
4. Kiểm tra điều khiển số 5 bật Stop thật: nếu đúng lúc đó có người khác đang xử lý email, ca của họ bị hủy (Stop hủy ca đang chạy dở).
5. Cụm cấm trong phản hồi tự động so khớp chuỗi con: "được miễn" cũng bắt cả "không được miễn" → có thể chuyển tiếp thừa (an toàn nhưng tốn nhân lực).
6. Tiền lọc injection dựa trên mẫu: có thể bỏ sót biến thể diễn đạt mới; lớp thứ hai là tín hiệu `suspect_input` của AI.
7. Ca kẹt ở PROCESSING (ví dụ redeploy giữa chừng) chỉ được tiếp quản khi có retry cùng khóa sau khi hết lease, hoặc nhân viên hủy; không có tiến trình nền tự quét.
8. Bảng kiểm tra điều khiển gọi tầng service trực tiếp thay vì HTTP (đã ghi ở 2e).
9. Phát hiện trùng nội dung (`NGHI_TRUNG`) chỉ trong 24 giờ và cùng nguồn.

## Việc người dùng cần làm tiếp
1. Đặt biến môi trường mới trên Railway (xem `.env.example`), deploy commit mới nhất.
2. `python scripts/run_dev_cases.py <URL> --out dev_run.json` → dán bảng kết quả (bắt buộc theo Mục 8; agent không tự chạy được).
3. Bấm 3 nút Verify trên Live URL; dán kết quả (hoặc `GET /api/verify-runs`).
4. Chạy 4 ca hold-out (agent không có) qua ô "Xử lý email".
5. Push lên GitHub (agent chưa push; không squash/force-push).

---

# Kiểm chứng mới trên Windows và Railway — 2026-10-17

**ĐÃ XÁC MINH:** mã nghiệp vụ từ `4e03a14`, đóng gói/deploy ở `77e73ed0258cccadca7f602c99358eebd5dead22`, Railway deployment `1200f92d-bf59-4086-9c42-047c19cf1c14` SUCCESS. URL: https://exodiaexe-production.up.railway.app. OpenAI và Supabase thật; email hoàn toàn giả lập. Không sửa prompt, gate, policy, ground truth hoặc kỳ vọng để chạy kiểm tra.

## Thiết lập và kiểm tra cục bộ

- Đã push lịch sử `d2347f7` → `4e03a14` và tài liệu cập nhật lên `origin/main`, không squash/force-push.
- Đã cấu hình Railway: `MAX_EMAIL_CHARS=4000`, `LLM_DAILY_CAP=300`, `VERIFY_DAILY_CAP=60`, `RATE_PER_IP_PER_MIN=6`, `LEASE_SECONDS=180`; giữ key/model/DB hiện có. Hai đơn giá bỏ trống, không tự bịa giá. 1 replica, Serverless tắt, Dockerfile, health `/api/health/ready`.
- Windows: `.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests tests_extra` → **56 passed, 12 skipped** (không đặt TEST_DATABASE_URL). `npm.cmd run build` → PASS. Bốn checksum protected và tên Brief trong Git đúng manifest. `git diff --check` PASS trước commit tài liệu.
- **CHƯA XÁC MINH lại 68/68:** lượt thử DB riêng trên Postgres 16.2/Windows không hoàn tất: lượt đầu có lỗi rồi bị ngắt khi treo; lượt khởi động lại pgserver gặp lỗi chia sẻ file `./log` / timeout pg_ctl. Chưa xác định nguyên nhân lượt test đầu; không quy lỗi này cho code sản phẩm. Đã dừng đúng Postgres của lượt thử, không xóa dữ liệu. Con số 68 PASS ở phần lịch sử vẫn là **ĐƯỢC BÁO CÁO bởi Cowork**.

## 11 ca dev qua HTTP / OpenAI thật

Lệnh thật: `python scripts/run_dev_cases.py https://exodiaexe-production.up.railway.app --out docs/validation/phase3-20261017/dev_run.json` (chạy bằng venv Python trên Windows). Không có ca HTTP 429, không chạy lại để chọn kết quả đẹp. Bắt đầu 06:15:06 UTC, kết thúc 06:17:43 UTC ngày 2026-10-17.

| Ca | Kết quả | Quyết định / lý do thực tế | Kiểm tra không đạt |
|---|---|---|---|
| C01 | PASS | AUTO | — |
| C02 | PASS | AUTO | — |
| C03 | PASS | AUTO | — |
| C05 | PASS | AUTO | — |
| C06 | FAIL | AUTO | 4. must_cite |
| C07 | PASS | ESCALATE / UNKNOWN_FACT | — |
| C09 | FAIL | ESCALATE / OUT_OF_POLICY | 2. reason_primary |
| C10 | FAIL | ESCALATE / OUT_OF_POLICY | 6. handoff_question |
| C12 | FAIL | ERROR | 0. không lỗi kỹ thuật; 1. decision; 2. reason_primary; 6. handoff_question |
| C14 | PASS | AUTO | — |
| C15 | PASS | AUTO | — |

**7/11 PASS, 4/11 FAIL; chưa nghiệm thu.** 94.297 token được ghi cho 10 ca có usage. C12 không có usage sau lỗi, nên tổng này thiếu lời gọi lỗi và không phải tổng chi phí/hóa đơn. Model trả về của các ca thành công là `gpt-6-luna`.

Phân tích chỉ đọc từ kết quả và audit ([chi tiết bốn ca lỗi](docs/validation/phase3-20261017/dev-fail-details.json)):

- C06: đúng AUTO nhưng chỉ cite D3.1 và D3.2.3.a; thiếu nhóm bắt buộc chứa D3.2.3.b hoặc D5.2.2.b. Gate kiểm mã tồn tại và phản hồi đủ điều kiện, không kiểm đủ các nhóm căn cứ của bộ chấm. Chưa kết luận chỉ do prompt.
- C09: package lưu `policy_gap=true`, `asks_determination=true`, `depends_on_unknown_fact=true`, không có GAP ID. Gate ưu tiên OUT_OF_POLICY đúng theo tín hiệu đầu vào, nhưng sai lý do chính so với kỳ vọng REQUIRES_HUMAN_AUTHORITY. Cần phân tích vì sao model bật policy_gap; không sửa thứ tự gate theo mã ca.
- C10: đúng ESCALATE/OUT_OF_POLICY, có GAP.PHULUC3, nhưng handoff_question không chứa "Phụ lục 3". Kiểm tra câu hỏi runtime chỉ bắt thiếu/ngắn/chung chung, không yêu cầu phản ánh gap cụ thể. Không thêm nhánh theo mã ca.
- C12: `LLM_OUTPUT_INVALID`, response.incomplete vì max_output_tokens, status ERROR; cờ SUSPECT_INPUT vẫn còn, **0 outbox**. Mã mặc định giới hạn 2000; Railway có biến giới hạn nhưng connector giấu giá trị, nên chưa xác minh số runtime. Lỗi xảy ra trước quyết định gate, không được coi là ESCALATE thành công. Lượt General riêng sau đó C12 PASS; không thay thế FAIL của lượt dev bằng lượt đó.

Chưa sửa chỉ dẫn hay logic nghiệp vụ. Phân tích trên mô tả đường gây lỗi đã quan sát; mọi đề xuất thay đổi phải được kiểm tra riêng, không đổi ground truth.

## Verify LIVE

| Bộ | Đạt | Thời lượng | Token ghi nhận | Run ID |
|---|---|---|---|---|
| GENERAL | 3/4 | 50181 ms | 38231 | `0a839279-1ff9-4a98-9f0c-cab1b9af6247` |
| ESCALATION | 3/5 | 67522 ms | 48568 | `cd99282a-4514-461e-a272-402467584986` |
| CONTROLS | 8/8 | 45263 ms | 27563 | `8037a153-f9d7-4f46-a1df-6178f26aa9f5` |

General: C01/C07/C12 PASS, C06 FAIL must_cite. Escalation: C02/C05/C15 PASS, C09 FAIL reason_primary, C10 FAIL handoff_question. Chỉ kiểm tra xác định đã được chấm; các mục duyệt nội dung bằng người vẫn **CHƯA DUYỆT**.

Nguồn bằng chứng: General là lượt đã xuất hiện trong `verify_runs`, được đọc qua GET `/api/verify-runs`; không ghi nhận là agent tự bấm thành công. Trình duyệt hiển thị UI Verify nhưng thao tác click/Enter bị lỗi dispatch/selector. Sau khi kiểm tra không có lượt trùng, agent chạy Escalation và Controls bằng POST `/api/verify/escalation` và `/api/verify/controls`. **Chưa xác minh được thao tác đủ ba nút bằng trình duyệt.** Chụp ảnh cuối qua CDP cũng timeout, không có ảnh kết quả để bàn giao.

Controls 8/8 trên Supabase thật: 1 ca/1 outbox khi replay; khác nội dung bị service từ chối 409; khóa mới có NGHI_TRUNG; hook lỗi finalize rollback về 0 outbox rồi retry có 1; Stop → PENDING_HUMAN/PAUSED; Hủy có audit; Override làm bản cũ SUPERSEDED và thêm CORRECTION; audit đủ trường. Các mục 1–3,5–8 ở mode=service, mục 4 mode=in-process. Dù POST để khởi động bộ Verify đi qua HTTP, **các bước kiểm tra bên trong không đi qua API HTTP như prompt yêu cầu**; 8/8 không chứng minh hợp đồng HTTP. Chưa có duyệt ngoại lệ mới từ người dùng.

Kết thúc: `/api/health/ready` HTTP 200; `/api/smoke/db` HTTP 404 (đã tắt); `paused=false`, public_used=11/300, verify_used=12/60. Bằng chứng JSON lưu trong `docs/validation/phase3-20261017/`.

## Hạ tầng Phase 1 đã kiểm trong phiên Codex trước

Đối chiếu log thật tại `.pytest_cache/railway-validation/` (ignored, không chứa trong Git): S1/S2/S3/S4/S5/S8 PASS ở `cf7b207`; S4 requested/returned `gpt-6-luna`, 3153 ms, 583 token; oldest_id `bd423d27-e5e7-4738-9e7a-3f634ed56ec0` còn sau redeploy (5 dòng). S7 bundle PASS, image secret scan NOT RUN. **S6 FAIL:** 4 probe, max **1835 ms**, ngưỡng 1000 ms. Log proxy 1–5 ms không thay thế số đo từ client. Lịch sử Cowork ghi người dùng cho qua S6; ngoại lệ đó là trạng thái được báo cáo, không phải PASS kỹ thuật. Chưa đo lại S6 ở bản nghiệp vụ mới, không tự thêm chẩn đoán/hạ ngưỡng.

## Phần còn lại / quyết định

- Bốn ca hold-out C04/C08/C11/C13: **NOT RUN**, do người giữ bộ ca tự nhập; agent không nhận/tìm/đoán nội dung.
- Cần người dùng quyết định chấp nhận Controls ở tầng service hay giữ yêu cầu HTTP. Hiện trạng chưa đáp ứng yêu cầu HTTP; không tự phê duyệt thay chủ sản phẩm.
- Có thể tiếp tục phân tích chỉ đọc các ca lỗi trước khi sửa prompt. Chưa thay chỉ dẫn, cấu hình token hay logic; không điều chỉnh theo mã ca, không sửa kỳ vọng.
- Giao diện nhân viên chưa có đăng nhập; người biết URL có thể Stop/Hủy/Override. Controls bật Stop thật, nên chạy tách khỏi xử lý email khác.

## Đầu ra nguyên trạng của lượt dev LIVE

```text
C01: PASS | thực=AUTO/None flags=[] | kỳ vọng=AUTO/None | lỗi: - | 12322ms
C02: PASS | thực=AUTO/None flags=[] | kỳ vọng=AUTO/None | lỗi: - | 10879ms
C03: PASS | thực=AUTO/None flags=[] | kỳ vọng=AUTO/None | lỗi: - | 11647ms
C05: PASS | thực=AUTO/None flags=[] | kỳ vọng=AUTO/None | lỗi: - | 13556ms
C06: FAIL | thực=AUTO/None flags=[] | kỳ vọng=AUTO/None | lỗi: ['4. must_cite'] | 12243ms
C07: PASS | thực=ESCALATE/UNKNOWN_FACT flags=[] | kỳ vọng=ESCALATE/UNKNOWN_FACT | lỗi: - | 12166ms
C09: FAIL | thực=ESCALATE/OUT_OF_POLICY flags=[] | kỳ vọng=ESCALATE/REQUIRES_HUMAN_AUTHORITY | lỗi: ['2. reason_primary'] | 20638ms
C10: FAIL | thực=ESCALATE/OUT_OF_POLICY flags=[] | kỳ vọng=ESCALATE/OUT_OF_POLICY | lỗi: ['6. handoff_question'] | 14299ms
C12: FAIL | thực=None/None flags=['SUSPECT_INPUT'] | kỳ vọng=ESCALATE/REQUIRES_HUMAN_AUTHORITY | lỗi: ['0. không lỗi kỹ thuật', '1. decision', '2. reason_primary', '6. handoff_question'] | 23875ms
C14: PASS | thực=AUTO/None flags=[] | kỳ vọng=AUTO/None | lỗi: - | 12604ms
C15: PASS | thực=AUTO/None flags=[] | kỳ vọng=AUTO/None | lỗi: - | 13293ms

Bắt đầu 2026-10-17T06:15:06.211633+00:00; xong 2026-10-17T06:17:43.734049+00:00
Đạt 7/11; tổng token 94297
```


---

# Sửa sau phân tích lỗi 11 ca dev — 2026-10-17 (người dùng đã duyệt đề xuất)

**Trạng thái: mã đã sửa, test xác định pass; CHƯA chạy lại với OpenAI thật** (môi trường agent bị chặn). Kết quả 7/11, General 3/4, Escalation 3/5 ở trên vẫn là kết quả của bản trước; không thay thế.

Nguyên nhân gốc (đọc từ `docs/validation/phase3-20261017/dev-fail-details.json`) và thay đổi:

| Ca | Nguyên nhân gốc | Thay đổi | Loại |
|---|---|---|---|
| C12 | `max_output_tokens=2000` tính cả token suy luận của model reasoning; đầu ra bị cắt (`response.incomplete`). C09 dùng 1561 token đầu ra cho một JSON ngắn ⇒ rủi ro chung cho mọi ca, không riêng C12. | Mặc định `LLM_MAX_OUTPUT_TOKENS` = 6000 (code + `.env.example`). Railway phải đổi biến nếu đang đặt 2000. | Cấu hình |
| C12 (phụ) | Lời gọi AI lỗi không có dòng audit và mất dấu lượt đã tính ngân sách. | Thêm audit `AGENT_CALL_FAILED` (mã lỗi, lượt thử, trần token; ghi rõ usage không lấy được từ lỗi SDK). | Code |
| C09 | AI đặt `policy_gap=true` (không có mã GAP) vì "quy chế không có điều khoản ngoại lệ", và `depends_on_unknown_fact=true` dù dữ kiện thiếu không đổi tuyến xử lý. | Chỉ dẫn: (1) không có điều khoản ngoại lệ ≠ khoảng trống; xin ngoại lệ ⇒ `asks_determination`; (2) `depends_on_unknown_fact` chỉ true khi dữ kiện thiếu làm đổi hướng/tuyến xử lý của DSA. Gate KHÔNG đổi. | Chỉ dẫn (quy tắc chung) |
| C10 | Chỉ dẫn không yêu cầu câu hỏi nêu nội dung bị dẫn chiếu mà thiếu. | Chỉ dẫn (3): khi `policy_gap`, câu hỏi phải gọi đúng tên nội dung quy chế dẫn chiếu mà không có và hỏi đúng thông tin thiếu. | Chỉ dẫn (quy tắc chung) |
| C06 | AI chỉ trích bước "lần đầu", thiếu bước tiếp theo. Kỳ vọng `must_cite` có thể tranh luận (email chỉ hỏi lần đầu) — chỉ báo cáo, không sửa ground truth. | **Không sửa** (quy tắc "nêu bước tiếp theo" dễ thành dạy theo đề; người dùng chưa chọn). Dự kiến vẫn FAIL. | — |

Không quy tắc nào nhắc mã ca hoặc chép email ground truth. Lưu ý trung thực: ví dụ "con số thực tế sau khi loại trừ theo quy chế" trong định nghĩa `depends_on_unknown_fact` (viết từ bản trước) được agent viết sau khi đã đọc bộ ca dev, nên có thể mang ảnh hưởng của C07.

**Controls qua HTTP:** bước 1–3, 5–8 nay gửi HTTP thật tới các route của chính ứng dụng (httpx `ASGITransport` trong tiến trình — đi qua đúng routing/validation/handler FastAPI), rồi đếm dòng DB. Bước 4 vẫn chèn lỗi bằng hook trong tiến trình, phần retry đi qua `POST /api/cases/{id}/retry`. Lời gọi nội bộ được nhận diện bằng một khóa trong ASGI scope do bộ bọc nội bộ đặt (không phải header/IP), nên client bên ngoài không giả mạo được; test chứng minh request ngoài gửi header cùng tên vẫn là `PUBLIC`. Lời gọi nội bộ được miễn giới hạn IP và tính vào hạn mức `llm:verify`. Không đi qua mạng/proxy Railway.

Bằng chứng (VM agent, Postgres 16 cục bộ): `python -m pytest -q tests tests_extra` → **69 passed**; `smoke_local.py` 11/11 PASS.

## Việc người dùng cần làm (theo thứ tự)
1. Nếu muốn số đo khái quát hóa sạch: chạy 4 ca hold-out trên bản đang deploy (`f3d8876`) TRƯỚC khi deploy bản sửa, ghi kết quả.
2. Railway: đặt `LLM_MAX_OUTPUT_TOKENS=6000` (hoặc xóa biến để dùng mặc định), deploy commit mới.
3. Chạy lại `python scripts/run_dev_cases.py <URL> --out docs/validation/<ngày>/dev_run.json`, 3 nút Verify, rồi 4 ca hold-out; dán kết quả. So với bảng cũ, đặc biệt C07 (quy tắc mới về `depends_on_unknown_fact` có thể làm lật).

---

# Kiểm chứng lại bản sửa 0d027bb — 2026-10-17

**ĐÃ XÁC MINH:** push `0d027bb52b087a06bc498f6c83817581f623ad1f` lên main; Railway deployment `8d92bd32-f1d5-46a2-a196-cbae254bddba` SUCCESS. Đặt `LLM_MAX_OUTPUT_TOKENS=6000` bằng Railway connector trước khi deploy (API xác nhận lưu và áp dụng lần deploy kế tiếp). Giữ nguyên gate, policy, manifest và kỳ vọng; bốn checksum đúng cả working tree lẫn Git blob tại SHA đã kiểm.

Người dùng chọn **triển khai ngay, bỏ baseline hold-out**. Sau các lượt kiểm, người dùng xác nhận **chưa chạy hold-out**. Cả baseline và bốn ca sau sửa đều NOT RUN; agent chỉ hướng dẫn thao tác, không nhận/tìm/đoán/tạo lại nội dung hoặc đáp án kín.

## Kiểm tra xác định

Windows: `.\.venv\Scripts\python.exe -X utf8 -u -m pytest -q tests tests_extra` → **56 passed, 13 skipped in 1.92s** khi không có TEST_DATABASE_URL. Lượt sandbox không trả output đã bị ngắt; kết quả trên là lượt chạy ngoài sandbox. Không dùng DB demo để chạy test DB có thay đổi dữ liệu. **69 PASS và smoke local PASS là kết quả người dùng/Cowork báo từ môi trường khác**, chưa được xác nhận lại đầy đủ trên Windows. Không build lại frontend cục bộ vì không có thay đổi frontend; Docker build Railway SUCCESS.

## Dev LIVE: 9/11

OpenAI và Supabase thật, dữ liệu email giả lập. Chạy đúng script một lượt, không đổi kỳ vọng và không chạy lặp để chọn kết quả. Thời gian 06:37:58–06:41:02 UTC. Có usage ở cả 11 ca, tổng ghi nhận **107.970 token**; không tự ước tính USD khi chưa đặt đơn giá. Mọi ca có NGHI_TRUNG do đã tồn tại nội dung trong cùng DB; cờ này được bộ chấm hiện hữu xem là thông tin, không bỏ qua lời gọi AI. Báo cáo cũ 7/11 được giữ nguyên.

| Ca | Bản trước 77e73ed | Bản sửa 0d027bb | Ghi chú lượt mới |
|---|---|---|---|
| C01 | PASS | PASS | — |
| C02 | PASS | PASS | — |
| C03 | PASS | PASS | — |
| C05 | PASS | PASS | — |
| C06 | FAIL | FAIL | 4. must_cite |
| C07 | PASS | FAIL | 2. reason_primary |
| C09 | FAIL | PASS | — |
| C10 | FAIL | PASS | — |
| C12 | FAIL | PASS | — |
| C14 | PASS | PASS | — |
| C15 | PASS | PASS | — |

Đọc package/audit trong `docs/validation/phase3-0d027bb-20261017/dev-selected-details.json`:

- **C06 vẫn FAIL:** cites D3.1 và D3.2.3.a, thiếu nhóm D3.2.3.b hoặc D5.2.2.b; không sửa kỳ vọng hoặc thêm luật theo mã ca.
- **C07 từ PASS thành FAIL:** AI trả `depends_on_unknown_fact=false`, `asks_determination=true`, `policy_gap=false`; gate không đổi chọn REQUIRES_HUMAN_AUTHORITY, trong khi kỳ vọng UNKNOWN_FACT. Ca vẫn PENDING_HUMAN, 0 outbox. Quan sát phù hợp với ảnh hưởng của chỉ dẫn mới giới hạn unknown_fact theo thay đổi hướng/tuyến xử lý; chưa có thử nghiệm tách riêng từng thay đổi nên chưa chứng minh quan hệ nhân quả hoàn toàn. General Verify cũng lặp lại lỗi này.
- **C09 PASS:** policy_gap=false, asks_determination=true, depends_on_unknown_fact=false; lý do chính REQUIRES_HUMAN_AUTHORITY.
- **C10 PASS:** policy_gap=true, GAP.PHULUC3, câu hỏi có tên Phụ lục 3; lý do chính OUT_OF_POLICY.
- **C12 PASS:** SUSPECT_INPUT, ESCALATE/REQUIRES_HUMAN_AUTHORITY, 0 outbox; không có response.incomplete trong hai lượt mới. Output usage ở dev là 1914 token, General 1351 token (đều dưới 2000), nên chưa thể quy thành công chỉ cho nâng trần 6000 hoặc coi lỗi cắt token đã bị loại bỏ vĩnh viễn.

Không sửa thêm prompt/logic trong phiên kiểm chứng này. Nhánh AGENT_CALL_FAILED đã đọc trong commit và có test được báo cáo; các lời gọi LIVE chính lần này đều thành công ở mức kỹ thuật nên chưa trực tiếp chứng minh nhánh lỗi SDK bằng lỗi LIVE mới.

## Ba bộ Verify LIVE

| Bộ | Trước | Mới | Thời lượng mới | Token ghi nhận | Run ID |
|---|---|---|---|---|---|
| GENERAL | 3/4 | 2/4 | 58720 ms | 39621 | `4e2545c2-76b5-47a0-b457-6f94880e1cb3` |
| ESCALATION | 3/5 | 5/5 | 71860 ms | 49403 | `0452a109-9168-4c9f-8017-499fd20dffcf` |
| CONTROLS | 8/8 (service/hook) | 8/8 | 51142 ms | 28172 | `c303da28-c614-45a2-a03f-7c1e3c7f7431` |

General: C01/C12 PASS, C06/C07 FAIL. Escalation: cả C02/C05/C15/C09/C10 PASS. Đây là các kiểm tra xác định; checklist nội dung cần người duyệt vẫn CHƯA DUYỆT. Hai lượt C09/C10 đạt chưa đủ kết luận ổn định hoặc khái quát hóa.

Controls 8/8: bước 1–3 và 5–8 có mode=http, đi qua route/validation/handler FastAPI bằng ASGITransport trong tiến trình. Bước 4 có mode="in-process (lỗi) + http (retry)": sau hook lỗi 0 outbox, retry HTTP200 có đúng 1 outbox. Các mã HTTP và số dòng DB được lưu nguyên trong JSON. Không qua mạng/proxy Railway ở từng bước; không coi hook chèn lỗi là request mạng thật. Test chống giả mạo dấu nội bộ nằm trong 13 test DB bị skip trên Windows; kết quả test đầy đủ ở VM là do người dùng báo cáo, chưa có kiểm tra giả mạo LIVE mới.

Thao tác bấm General Verify bằng công cụ trình duyệt bị lỗi trước dispatch; kiểm tra lịch sử chưa có lượt mới rồi dùng POST `/api/verify/general`, `/escalation`, `/controls`. **Chưa xác minh đủ ba nút UI bằng thao tác trình duyệt.** Không dựng ảnh hoặc kết quả UI để thay thế bằng chứng này.

Có thêm lượt Controls `643cdc26-1a58-46ce-8dbd-5930b7258094` đạt 8/8 xuất hiện trong DB; nguồn kích hoạt chưa xác minh, lưu riêng ở `verify-additional-observed.json`, không gộp vào ba lượt chính. Snapshot sau kiểm: public_used=23/300, verify_used=27/60; bộ đếm có cả lịch sử và lượt bổ sung, không phải chỉ lượt chính. `/api/health/ready`=200, smoke DB=404, paused=false.

## Còn lại

- Bốn hold-out NOT RUN (người dùng xác nhận); hướng dẫn tự chạy, ghi kết quả lần đầu và chỉ gửi bảng đạt/lỗi, không gửi nội dung/đáp án kín. Không chạy Controls đồng thời với hold-out.
- S6 bản mới NOT RUN; FAIL 1835 ms của bản trước vẫn được giữ nguyên, không chuyển thành PASS. Image secret scan chưa chạy lại.
- C06 chưa sửa; C07 là hồi quy về lý do chính. Chưa chỉnh thêm chỉ dẫn sau kết quả này. C09/C10 đã đạt ở hai lượt nên chưa phát sinh điều kiện "nếu còn sai" để tiếp tục chỉnh.
- Giao diện nhân viên vẫn chưa có đăng nhập. Kết quả hiện tại chưa đủ nghiệm thu hoặc xác nhận tổng quát hóa.

## Đầu ra nguyên trạng của lượt dev mới

```text
C01: PASS | thực=AUTO/None flags=['NGHI_TRUNG'] | kỳ vọng=AUTO/None | lỗi: - | 14962ms
C02: PASS | thực=AUTO/None flags=['NGHI_TRUNG'] | kỳ vọng=AUTO/None | lỗi: - | 12998ms
C03: PASS | thực=AUTO/None flags=['NGHI_TRUNG'] | kỳ vọng=AUTO/None | lỗi: - | 15147ms
C05: PASS | thực=AUTO/None flags=['NGHI_TRUNG'] | kỳ vọng=AUTO/None | lỗi: - | 14645ms
C06: FAIL | thực=AUTO/None flags=['NGHI_TRUNG'] | kỳ vọng=AUTO/None | lỗi: ['4. must_cite'] | 18758ms
C07: FAIL | thực=ESCALATE/REQUIRES_HUMAN_AUTHORITY flags=['NGHI_TRUNG'] | kỳ vọng=ESCALATE/UNKNOWN_FACT | lỗi: ['2. reason_primary'] | 17299ms
C09: PASS | thực=ESCALATE/REQUIRES_HUMAN_AUTHORITY flags=['NGHI_TRUNG'] | kỳ vọng=ESCALATE/REQUIRES_HUMAN_AUTHORITY | lỗi: - | 15355ms
C10: PASS | thực=ESCALATE/OUT_OF_POLICY flags=['NGHI_TRUNG'] | kỳ vọng=ESCALATE/OUT_OF_POLICY | lỗi: - | 22134ms
C12: PASS | thực=ESCALATE/REQUIRES_HUMAN_AUTHORITY flags=['NGHI_TRUNG', 'SUSPECT_INPUT'] | kỳ vọng=ESCALATE/REQUIRES_HUMAN_AUTHORITY | lỗi: - | 24365ms
C14: PASS | thực=AUTO/None flags=['NGHI_TRUNG'] | kỳ vọng=AUTO/None | lỗi: - | 12591ms
C15: PASS | thực=AUTO/None flags=['NGHI_TRUNG'] | kỳ vọng=AUTO/None | lỗi: - | 15151ms

Bắt đầu 2026-10-17T06:37:58.699334+00:00; xong 2026-10-17T06:41:02.103401+00:00
Đạt 9/11; tổng token 107970
```
