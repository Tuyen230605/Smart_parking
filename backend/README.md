# Backend

Xử lý sự kiện Pi và cảm biến; quản lý phiên đỗ; gán ô bằng dữ liệu trạng thái mới nhất; phát lệnh cần chắn; gửi chỉ dẫn và thông báo.

Các thao tác cần idempotent theo `event_id`/`command_id`. Chỉ mở cổng sau khi kiểm tra nghiệp vụ. Tách adapter local/mock khỏi adapter AWS IoT, SES và SNS/nhà cung cấp SMS.
