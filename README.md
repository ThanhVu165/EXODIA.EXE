# DSA Intelligence — Đề A (The Escalation Referee), MLAI Hackathon 2026

> **Bản demo/sandbox. Dữ liệu giả lập. Không phải hệ thống chính thức của UEH.** Không gửi email thật: "gửi phản hồi" = ghi vào bảng `outbox` và hiển thị trên giao diện.

Hệ thống hỗ trợ nhân viên Ban chăm sóc người học (DSA) trả lời email thắc mắc của sinh viên về đạo văn và sử dụng AI
trong sản phẩm học thuật, dựa trên **nguyên văn** Quy định kèm QĐ 4002/QĐ-ĐHKT-NCPTGKTC của UEH (`policy/QD4002_UEH.md`).

- **AUTO**: thắc mắc thường quy mà quy chế trả lời được → trả lời có căn cứ điều khoản.
- **ESCALATE**: thiếu dữ kiện (`UNKNOWN_FACT`), ngoài quy chế (`OUT_OF_POLICY`), hoặc cần người có thẩm quyền
  (`REQUIRES_HUMAN_AUTHORITY`) → chuyển nhân viên DSA kèm **một câu hỏi cụ thể** và gói quyết định.
- Email có dấu hiệu chỉ dẫn nhắm vào hệ thống → cờ `SUSPECT_INPUT`, luôn chuyển tiếp, chặn bản trả lời.

## Ai quyết định gì
AI (OpenAI, qua Agents SDK) chỉ **trích xuất, tìm căn cứ, soạn nháp, gợi ý**. Quyết định AUTO/ESCALATE do **bộ quy tắc
bằng code** (`backend/app/gate.py`). Nhân viên DSA quyết định mọi ca chuyển tiếp, có thể **Dừng hệ thống**, **Hủy**,
**Override** (đính chính phản hồi tự động), và xem **nhật ký kiểm toán** (chỉ thêm) cho bất kỳ ca nào.

## Phần nào thật, phần nào giả lập
| Thành phần | Thật / giả lập |
|---|---|
| Văn bản quy chế UEH (QĐ 4002) | Thật — nguyên văn, nguồn chính sách duy nhất; phiên bản = sha256 file |
| Danh mục mã điều khoản, khoảng trống chính sách (`ground_truth/clause_ids.yaml`) | Do đội biên soạn từ văn bản thật |
| Email sinh viên trong bộ ca dev/Verify (`ground_truth/cases_dev.yaml`) | **Giả lập** (tên, MSSV hư cấu) |
| Gọi AI (OpenAI), cơ sở dữ liệu (Supabase PostgreSQL), triển khai (Railway) | Thật |
| Gửi email | **Không có** — chỉ ghi `outbox` |
| Người dùng/nhân viên DSA | Không có người dùng thật; giao diện nhân viên dùng không cần tài khoản (demo) |

## Kiến trúc
Một container Docker trên Railway: FastAPI (1 tiến trình Uvicorn) phục vụ API và frontend Next.js static export;
Supabase PostgreSQL qua Session Pooler (5432, SSL). Xem `RUNBOOK.md` để chạy, `PROGRESS.md` cho trạng thái, bằng chứng và
giới hạn, `docs/AI_USAGE.md` cho việc dùng công cụ AI khi phát triển.
