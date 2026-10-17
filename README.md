# DSA Intelligence — Đề A (The Escalation Referee), MLAI Hackathon 2026

> **Bản demo/sandbox. Dữ liệu giả lập. Không phải hệ thống chính thức của UEH.** Không gửi email thật: "gửi phản hồi" = ghi vào bảng `outbox` và hiển thị trên giao diện.

Live URL: https://exodiaexe-production.up.railway.app. Trạng thái và commit đã kiểm chứng được ghi trong `PROGRESS.md`; có URL hoạt động chưa đồng nghĩa tất cả ca nghiệp vụ đều đạt.

Kiểm chứng LIVE ngày 2026-10-17 ở commit `0d027bb`: **11 ca dev đạt 9/11** với OpenAI thật; C06 và C07 FAIL, C09/C10/C12 PASS trong lượt này. Báo cáo mới ở `docs/validation/phase3-0d027bb-20261017/`. Giữ nguyên lượt cũ 7/11 trong `docs/validation/phase3-20261017/`; một lượt chưa chứng minh độ ổn định. Chưa nghiệm thu; xem PROGRESS cho Verify và các phần chưa kiểm.

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

## Chạy thử và giới hạn bàn giao

Xem `RUNBOOK.md` để nạp `.env.local`, chạy trên Windows/Linux, deploy, chạy 11 ca dev qua HTTP với OpenAI thật và ba nút Verify. Verify có hạn mức riêng; mọi email của bộ dev/Verify đều là dữ liệu giả lập.

Các test dùng FixedAgent chỉ xác minh cơ chế trạng thái, DB và audit; kết quả phân loại cần được xác minh bằng model thật. Controls hiện đi qua route HTTP bằng ASGITransport trong tiến trình; bước 4 dùng hook lỗi rồi retry qua HTTP. Bộ này không đo mạng/proxy Railway. Bốn ca hold-out do người giữ bộ ca tự chạy, không cung cấp cho agent.

Giao diện nhân viên hiện không có đăng nhập; người biết URL có thể thao tác Stop/Hủy/Override. Stop hủy ca đang xử lý dở và giữ hàng chờ nhân viên. Đây là giới hạn của demo, không phải mô hình phân quyền để triển khai nghiệp vụ thật.


## Challenge bổ sung: đánh giá mức hài lòng DỰ ĐOÁN (Agent 2)
- Sau khi một phản hồi **tự động** được ghi outbox, backend gọi **Agent 2** (prompt riêng, lời gọi riêng, chạy nền)
  để dự đoán mức hài lòng của sinh viên, thang 0–100, kèm giải thích và các ý còn thiếu.
- **Điểm do AI dự đoán — không phải khảo sát sinh viên.** Không có sinh viên thật trong demo.
- Chỉ chấm phản hồi tự động (kể cả bản về sau bị nhân viên đính chính). Không chấm ca chuyển tiếp, phản hồi do nhân
  viên viết, hay dữ liệu Verify. Báo cáo Satisfaction **không** thay báo cáo Escalation/Verify.
- Agent 2 **không** sửa phản hồi, không gửi thêm, không phê duyệt, không đổi prompt hay quy chế. Lỗi chấm được ghi
  `EVALUATION_FAILED`/`INSUFFICIENT_CONTEXT`, không bao giờ thành 0 điểm.
- Báo cáo theo ngày (giờ Việt Nam) được **tính trực tiếp khi mở** (tab "Đánh giá phản hồi (dự đoán)" hoặc
  `GET /api/reports/daily`), không có lịch tự chạy cuối ngày. DSA chọn Đồng ý / Không đồng ý kèm nhận xét; mọi lượt chấm
  và rà soát được ghi audit.
- Kiến trúc thật: Agent 1 nhận **toàn văn quy chế** làm ngữ cảnh (không dùng RAG); căn cứ hiển thị và căn cứ đưa cho
  Agent 2 đều do code trích nguyên văn theo mã điều khoản.
