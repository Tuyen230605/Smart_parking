# Smart Parking — đồ án bãi đỗ xe thông minh

Mô hình bãi **2 tầng, 18 ô** kết hợp Raspberry Pi 5/camera, hai ESP32, AWS và một web app. Pi nhận diện thẻ xanh/đỏ và biển số; ESP32 cổng điều khiển **hai cần chắn + OLED**; ESP32 ô đọc **một cảm biến thật + 17 nút giả lập**. Backend gán ô, hiển thị QR riêng cho từng lượt, gửi email hướng dẫn nếu khách nhập email, và tính phí mô phỏng lúc ra.

> Repository hiện là **thiết kế và khung module**, chưa phải phần mềm/firmware chạy hoàn chỉnh.

## Đọc theo thứ tự

| Tài liệu | Nội dung |
|---|---|
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | Mục tiêu, phạm vi, mốc và phân công 4 người |
| [docs/architecture.md](docs/architecture.md) | Kiến trúc đầu cuối, phần mềm trên AWS, dữ liệu và quyết định thiết kế |
| [docs/parking-layout.md](docs/parking-layout.md) | Sơ đồ hai làn, hai tầng, 18 ô và đường đi |
| [docs/use-cases.md](docs/use-cases.md) | 10 kịch bản chi tiết: vào/ra, email, tính phí, lỗi, lưu 10 ngày |
| [docs/mqtt-contract.md](docs/mqtt-contract.md) | Topic và JSON giữa Pi, ESP32, AWS |
| [docs/api-contract.md](docs/api-contract.md) | API web khách/kiosk/quản trị và mô hình dữ liệu |
| [docs/hardware-and-budget.md](docs/hardware-and-budget.md) | Linh kiện, đấu nối và giá tham khảo |
| [docs/aws-deployment.md](docs/aws-deployment.md) | Tài nguyên AWS và thứ tự triển khai |
| [docs/simulation-and-test-plan.md](docs/simulation-and-test-plan.md) | Mô phỏng 17 nút và nghiệm thu đầu cuối |

DOCX gốc nằm tại thư mục gốc để tham khảo định hướng ban đầu. Tài liệu Markdown trên là thiết kế MVP đã cập nhật theo phạm vi phần cứng hiện tại; các số liệu Free Tier trong DOCX không dùng làm cam kết chi phí.

## Luồng chính

1. Pi thấy **thẻ xanh ở làn vào** và đọc biển số → backend giữ một ô trống → mở cần vào.
2. OLED hiện ô/đường; kiosk trên laptop/tablet hiện **QR của phiên**. Khách xem đường ngay và có thể nhập email để nhận hướng dẫn qua Amazon SES. Không nhập email vẫn đỗ được.
3. ESP32 ô báo xe vào ô (một sensor thật hoặc nút giả lập) → phiên thành `PARKED`.
4. Pi thấy **thẻ đỏ ở làn ra** → backend tính phí demo → quản trị xác nhận thu tiền → mở cần ra → quản trị xác nhận xe đã qua.
5. Dữ liệu định danh, gồm biển số và email, không lưu quá 10 ngày từ lúc thu thập.

## Cấu trúc repository

```text
docs/                       tài liệu hệ thống và hợp đồng
edge/raspberry-pi-vision/   camera, thẻ màu, OCR
firmware/esp32-gates/       2 cần chắn, OLED
firmware/esp32-slot-sensors/ 1 cảm biến, 17 nút
backend/                    phiên đỗ, ô, QR, giá, email
web/                        một app cho guest/kiosk/admin
simulation/                 mock device và kịch bản
infra/aws/                  cấu hình AWS theo tài liệu triển khai
```

## Nguyên tắc triển khai

- Thống nhất schema v1 ở [MQTT](docs/mqtt-contract.md) và [API](docs/api-contract.md) trước khi viết firmware/backend.
- Dựng mock thiết bị để web/backend chạy được khi chưa có sa bàn.
- Không commit private key/certificate, AWS secret hoặc dữ liệu khách thật.
- Web không điều khiển ESP trực tiếp; backend kiểm tra nghiệp vụ rồi mới phát lệnh.
- Giữ tính phí ở chế độ mô phỏng và xác nhận thu tiền thủ công; không tự nhận là đã thanh toán online.
