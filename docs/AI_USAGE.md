# Minh bạch việc sử dụng AI

| Ngày | Công cụ AI | Mục đích | Phần do AI tạo | Cách kiểm chứng |
|---|---|---|---|---|
| 2026-10-17 | Claude (Anthropic) trong Cowork | Agent triển khai Giai đoạn 1 theo `BUILD_PROMPT_COWORK.md` (preflight + smoke hạ tầng) | `docs/PREFLIGHT.md`, khung `backend/app/*`, `tests/*`, `scripts/*`, khung `frontend/*`, `Dockerfile`, `.dockerignore`, `.gitignore`, `.env.example`, `railway.json`, `RUNBOOK.md`, `PROGRESS.md` | `pytest`, `scripts/smoke_local.py` chạy thật trên VM cục bộ; S1/S3/S4/S6/S8 do người dùng chạy trên máy/Railway và báo lại (ghi rõ trong PROGRESS) |
| 2026-10-17 | Claude (Anthropic) trong Cowork | Giai đoạn 2–3: nghiệp vụ, Verify, giao diện, tài liệu | `backend/app/{schema.sql,policy.py,prompts.py,prefilter.py,gate.py,agent.py,service.py,budget.py,api.py,verify.py,verify_checks.py}`, `frontend/{app,components,lib}`, `tests/*`, `tests_extra/*`, `scripts/run_dev_cases.py`, `README.md`, cập nhật `RUNBOOK.md` | 68 test xác định (gồm test DB trên Postgres 16 cục bộ); build frontend; tự xem giao diện bằng Chromium headless. **Chưa kiểm chứng với OpenAI thật và Supabase** tại môi trường agent (bị chặn mạng) — xem PROGRESS |
| — | OpenAI (`OPENAI_MODEL`, dự kiến `gpt-6-luna`) | Thành phần của sản phẩm khi chạy: trích xuất, tìm căn cứ, soạn nháp | Không sinh code | Quyết định do gate bằng code; Verify chấm bằng kiểm tra xác định |
