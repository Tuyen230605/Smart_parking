# Kế hoạch dự án

## Mục tiêu

Làm một hệ thống bãi đỗ xe thông minh chạy trên AWS, trình diễn trên sa bàn 2 tầng, 18 ô. Hệ thống phải chạy được trọn một vòng: xe vào (nhân viên cho vào), khách xem chỗ trống và đường đi, xe ra (tính tiền, thu tiền, cho ra).

## Phạm vi

| Phần | Nội dung |
|---|---|
| Camera | Một camera trên Pi 5 nhìn hai làn. Có vật trong làn là có xe. Biển số do hệ thống cấp (11111, 22222, ...) |
| Cổng | ESP32-S3 điều khiển một servo làm cần chắn: quay trái là mở vào, quay phải là mở ra |
| Ô đỗ | ESP32 đọc 18 nút giả lập cảm biến có xe, chỉ để biết chỗ trống |
| Đám mây | IoT Core, Lambda, DynamoDB, API Gateway, Cognito, SES, S3, CloudFront, EventBridge, CloudWatch, Budgets |
| Web | Sơ đồ bãi, kiosk QR, trang khách (chọn ô, đường đi, email), trang quản trị |

Ngoài phạm vi: thanh toán trực tuyến, đọc biển số thật, cảm biến xe thật, ứng dụng di động, nhiều bãi.

## Mốc thực hiện

| Giai đoạn | Kết quả | Mốc |
|---|---|---|
| 1. Khởi động | Ý tưởng, sơ đồ bãi 18 ô | 30/09/2026 |
| 2. Phân tích, đề xuất giải pháp | Kiến trúc, định dạng tin nhắn và API, chi phí ước tính | 05/10/2026 |
| 3. Phần mềm thiết bị và web | Chương trình trên Pi, ứng dụng web | 27/10/2026 |
| 4. Phần đám mây | Template CloudFormation, 3 Lambda, chương trình giả lập, firmware ESP32 | 08/11/2026 |
| 5. Triển khai AWS, kiểm thử tích hợp | Hệ thống chạy trên AWS | 14/11/2026 |
| 6. Lắp thiết bị thật | Pi, camera, hai ESP32 kết nối AWS, chạy thử trọn luồng | 27/11/2026 |
| 7. Nghiệm thu, bàn giao | Báo cáo, video demo, tài liệu | Buổi bảo vệ |

## Tiêu chí hoàn thành

- 16 kịch bản trong [docs/simulation-and-test-plan.md](docs/simulation-and-test-plan.md) đều đạt.
- Toàn bộ hạ tầng dựng và gỡ được bằng script.
- Dữ liệu cá nhân bị xóa sau tối đa 10 ngày.
- Có tài liệu cài đặt, vận hành và báo cáo.
