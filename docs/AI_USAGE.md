# Minh bạch việc sử dụng AI

| Ngày | Công cụ AI | Mục đích | Phần do AI tạo | Cách kiểm chứng |
|---|---|---|---|---|
| 2026-10-17 | Claude (Anthropic) trong Cowork, cấu hình model `claude-opus-5-5` | Agent triển khai Giai đoạn 1 theo `BUILD_PROMPT_COWORK.md` (preflight + smoke hạ tầng) | `docs/PREFLIGHT.md`, `backend/app/*`, `backend/requirements*.txt`, `tests/*`, `scripts/*`, `frontend/*` (khung), `Dockerfile`, `.dockerignore`, `.gitignore`, `.env.example`, `railway.json`, `RUNBOOK.md`, `PROGRESS.md`, file này | Chạy thật `pytest` (21 test) và `scripts/smoke_local.py` trên VM cục bộ; đầu ra lưu trong `PROGRESS.md`. Các mục không chạy được (Docker build, Supabase, OpenAI) được ghi BLOCKED, không tuyên bố pass. |
