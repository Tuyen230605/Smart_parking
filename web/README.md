# Web dùng chung cho khách, kiosk và quản trị

Một ứng dụng responsive, ba chế độ:

- Public/guest: sơ đồ 18 ô; trang QR phiên cho biết ô/đường và form email tùy chọn.
- Kiosk tại cổng: hiển thị QR phiên đang vào trên laptop/tablet, không hiện dữ liệu riêng của xe khác.
- Admin: đăng nhập Cognito, theo dõi thiết bị/phiên, xử lý OCR, phí và xác nhận xe đã ra.

Web dùng [REST API](../docs/api-contract.md); không nhúng AWS secret hoặc subscribe IoT Core trực tiếp.
