# Bằng chứng LIVE — 2026-10-17

Mã đã kiểm: `77e73ed0258cccadca7f602c99358eebd5dead22`.
Railway deployment `1200f92d-bf59-4086-9c42-047c19cf1c14`: SUCCESS.
URL: https://exodiaexe-production.up.railway.app.
OpenAI/Supabase thật, email giả lập; chưa nghiệm thu. Xem [báo cáo và phân tích](../../../PROGRESS.md).

- [metadata.json](metadata.json): SHA, thời gian và giới hạn bằng chứng.
- [dev_run.log](dev_run.log), [dev_run.json](dev_run.json): đầu ra nguyên trạng 11 ca; 7 PASS, 4 FAIL.
- [dev-fail-details.json](dev-fail-details.json): package, outbox và audit của 4 ca lỗi.
- [verify-runs.json](verify-runs.json): General 3/4, Escalation 3/5, Controls 8/8.
- [verify-observed.json](verify-observed.json): General đã lưu trước khi agent gọi các endpoint còn lại; không phải bằng chứng agent tự bấm nút.
- [verify-escalation.json](verify-escalation.json), [verify-controls.json](verify-controls.json): phản hồi POST LIVE.
- [system-before.json](system-before.json), [system-after.json](system-after.json): cấu hình công khai, hạn mức, trạng thái Stop.

Controls kiểm tầng service/hook, chưa đáp ứng kiểm thử HTTP từng thao tác. Thao tác đủ ba nút UI chưa xác minh do lỗi điều khiển trình duyệt. 4 hold-out NOT RUN; các checklist duyệt tay CHƯA DUYỆT. Token ghi nhận thiếu usage của C12 lỗi, không phải tổng hóa đơn.
