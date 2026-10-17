# Bằng chứng kiểm lại 0d027bb — 2026-10-17

OpenAI/Supabase thật, email giả lập. Tested SHA `0d027bb52b087a06bc498f6c83817581f623ad1f`; Railway deployment `8d92bd32-f1d5-46a2-a196-cbae254bddba` SUCCESS; token cap được đặt 6000.

- [metadata.json](metadata.json): SHA, cấu hình, thời gian, run ID, giới hạn bằng chứng.
- [dev_run.log](dev_run.log), [dev_run.json](dev_run.json): lượt mới 9/11; C06 và C07 FAIL. Không thay lượt cũ 7/11.
- [dev-selected-details.json](dev-selected-details.json): package/audit của C06/C07/C09/C10/C12.
- [verify-runs.json](verify-runs.json): ba lượt chính General 2/4, Escalation 5/5, Controls 8/8; phản hồi POST lưu riêng theo tên bộ.
- [verify-before.json](verify-before.json): lịch sử trước lượt General, tránh chạy trùng sau lỗi thao tác trình duyệt.
- [verify-additional-observed.json](verify-additional-observed.json): Controls bổ sung 8/8, không gán nguồn kích hoạt.
- [system-before.json](system-before.json), [system-after.json](system-after.json): snapshot trạng thái và bộ đếm.

Xem [PROGRESS](../../../PROGRESS.md) cho bảng so sánh, lệnh và phân tích. Controls dùng HTTP trong ASGI process (bước 4 có hook); không đo mạng Railway. Ba nút UI chưa được xác minh. Hold-out trước/sau đều NOT RUN theo người dùng; checklist duyệt tay chưa duyệt. C07 là hồi quy; chưa nghiệm thu.
