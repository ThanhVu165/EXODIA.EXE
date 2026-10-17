# PREFLIGHT — kiểm tra năng lực môi trường (Mục 4)

Ngày chạy: 2026-10-17 (giờ VN). Người chạy: agent triển khai (Claude trong Cowork).
Mọi kết quả dưới đây là đầu ra thật của lệnh đã chạy; không có mục nào được suy đoán.

Agent có **hai** môi trường thực thi:
- **VM-local** = máy ảo Linux trên máy của người dùng, thư mục dự án mount tại `~/mnt/EXODIA.EXE` (nơi làm việc chính).
- **Cloud** = container đám mây của phiên Cowork (không thấy thư mục dự án trừ khi chuyển file).
Cả hai đi ra mạng qua proxy egress theo cài đặt của tài khoản.

| # | Năng lực | Cách kiểm | Kết quả thật |
|---|---|---|---|
| 1 | Ghi/đọc file trong thư mục dự án | `echo t > .pf_write_test && cat .pf_write_test` | **CÓ** (đọc lại `t`). Xóa file ban đầu bị chặn (`Operation not permitted`); người dùng đã cấp quyền xóa cho phiên, file thử đã được xóa. |
| 2 | Python | `python3 --version` | VM-local: Python 3.10.12 (hệ thống); đã cài thêm CPython **3.12.14** qua `uv python install 3.12` để khớp image runtime. Cloud: 3.13.16 |
| 3 | Node / npm | `node --version; npm --version` | VM-local: Node v22.23.2, npm 10.9.8 |
| 4 | Docker CLI | `docker --version` | VM-local: **KHÔNG** (`docker: command not found`). Cloud: Docker 29.8.2, daemon khởi động được |
| 5 | `docker build` chạy được không | Cloud: `docker pull python:3.12-slim`, `mirror.gcr.io/...`, `public.ecr.aws/...` | **KHÔNG**: mọi registry trả `Forbidden` qua proxy egress → không kéo được base image → `docker build` **BLOCKED** ở cả hai môi trường |
| 6 | git | `git --version; git status; git remote -v` | git 2.34.1. Repo đã `init`, nhánh `main`, **chưa có commit**, remote `origin = https://github.com/ThanhVu165/EXODIA.EXE.git`. `user.name`/`user.email` **chưa cấu hình** |
| 7 | pip → PyPI | `curl https://pypi.org/simple/fastapi/` + `uv pip install fastapi uvicorn psycopg openai-agents ...` | **CÓ** (HTTP 200; cài thành công: openai-agents 0.24.0, openai 3.33.0, fastapi 0.143.3, uvicorn 0.54.0, psycopg 3.3.6, pydantic 2.14.1) |
| 8 | npm registry | `curl https://registry.npmjs.org/next`; `npm view next version` | **CÓ** (HTTP 200; `next` mới nhất = 16.4.2) |
| 9 | `api.openai.com` | `curl -m 15 https://api.openai.com/v1/models` (cả VM-local và Cloud) | **KHÔNG**: curl rc=56; proxy ghi `gateway answered 403 to CONNECT (policy denial) host api.openai.com:443` |
| 10 | TCP tới Supabase Session Pooler :5432 | Python `socket.create_connection(("aws-0-ap-southeast-1.pooler.supabase.com",5432))` (host mẫu; chưa có `DATABASE_URL` thật) | **KHÔNG**: `Temporary failure in name resolution` (VM-local), `Name or service not known` (Cloud); `https://supabase.com` cũng bị proxy 403 |
| 11 | Đọc file Mục 3 | `ls`, `sha256sum -c`, parse YAML | **CÓ** (xem ghi chú A, B) |
| 12 | Checksum `GROUND_TRUTH.sha256` | `tr -d '\r' < GROUND_TRUTH.sha256 \| sha256sum -c` | **4/4 OK** sau khi bỏ `\r` (xem ghi chú A) |
| 13 | Anchor trong `clause_ids.yaml` có trong policy (chuẩn hóa khoảng trắng) | Python: `re.sub(r'\s+',' ',...)` rồi `in` | **40/40 clause + 3/3 gap khớp**, không trùng id |
| 14 | Postgres cục bộ để tự kiểm | `uv pip install pgserver` → PostgreSQL 16.2 (unix socket, trong VM-local) | **CÓ** — chỉ dùng thay thế cho kiểm thử cục bộ; **không** phải Supabase, không chứng minh S3 |
| 15 | `.env.local` / secret | `ls -a` | Không có `.env.local` trong dự án (đúng như mong đợi; agent không cần và không đọc key) |

## Ghi chú phát hiện (báo cáo, không tự sửa)

A. **`GROUND_TRUTH.sha256` dùng CRLF.** `sha256sum -c GROUND_TRUTH.sha256` chạy thẳng trên Linux sẽ FAIL (tên file dính `\r`). Test toàn vẹn sẽ đọc file và bỏ `\r` cuối dòng — đây là xử lý định dạng dòng, không nới kiểm tra hash.

B. **Sai khác hoa/thường tên file Brief.** `GROUND_TRUTH.sha256` và BUILD_PROMPT ghi `docs/BRIEF_OrganizationAI_VN.md`, file thật là `docs/Brief_OrganizationAI_VN.md`. Trên Windows (không phân biệt hoa/thường) vẫn mở được, nhưng **trong Docker/Railway (Linux) và khi clone repo trên Linux, đường dẫn `docs/BRIEF_...` sẽ không tồn tại** → test toàn vẹn sẽ fail. Người dùng cần quyết định: đổi tên file thành `BRIEF_...` hoặc sửa dòng trong `GROUND_TRUTH.sha256` (cả hai đều là file chỉ người dùng được sửa).

C. **Policy file không ở dạng Unicode NFC** (`unicodedata.is_normalized('NFC', p) == False`). Anchor vẫn khớp vì YAML cùng dạng. Hệ quả cho Giai đoạn 2: so khớp chuỗi tiếng Việt từ email (trình duyệt thường gửi NFC) với văn bản quy chế phải chuẩn hóa NFC hai phía ở tầng code; không sửa policy file.

D. Có file `docs/desktop.ini` (file hệ thống Windows) — nên đưa vào `.gitignore`.

## Hệ quả cho kế hoạch (việc chuyển sang người dùng)

| Năng lực thiếu | Ảnh hưởng | Ai làm, làm thế nào |
|---|---|---|
| Không `docker build` được | S1 BLOCKED; Dockerfile viết nhưng **CHƯA KIỂM CHỨNG** | Người dùng: `docker build` trên máy có Docker, **hoặc** để Railway build (log build Railway là bằng chứng S1) |
| Không gọi được OpenAI | S4 và phần "LLM thật" của S6 BLOCKED tại đây | Người dùng chạy `scripts/smoke_remote.py <URL> --smoke-token ...` sau khi deploy Railway (Railway có egress tự do), hoặc chạy `scripts/smoke_local.py --llm` trên máy có mạng tới OpenAI |
| Không tới được Supabase | S3 BLOCKED tại đây; S5 chỉ kiểm được với Postgres cục bộ | Người dùng chạy smoke từ xa (endpoint `/api/smoke/db`) trên Railway |
| git chưa có danh tính | Agent không tự đặt `user.name/email` thay người dùng | Người dùng cấu hình git hoặc cho phép agent commit với danh tính nào (hỏi ở báo cáo) |
| Egress khác nhau giữa môi trường | Lỗi mạng trên Railway sẽ khác ở đây | S8 do người dùng chạy và dán kết quả |
