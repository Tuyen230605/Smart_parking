# Smart Parking — đồ án bãi đỗ xe thông minh

Mô hình bãi **2 tầng, 18 ô** kết hợp Raspberry Pi 5/camera, hai ESP32, AWS và một web app. Pi phát hiện **có xe ở làn vào/ra** (đưa tay/xe mô hình vào khung camera); ESP32 cổng điều khiển **một servo cần chắn 3 vị trí + OLED**; ESP32 ô đọc **18 nút bấm** để chỉ chỗ trống. Quản trị bấm **Cho vào / Cho ra** trên web thì cần mới mở; backend đánh biển số demo, gợi ý ô trống + vẽ đường đi trên trang QR, gửi email hướng dẫn (tùy chọn ghi nhớ email theo biển số) và tính phí mô phỏng lúc ra.

> **Dựng lên AWS: [docs/setup-guide.md](docs/setup-guide.md)** — backend, hạ tầng (CloudFormation), web, Pi, mock 2 ESP32 và firmware ESP32 đều đã có code chạy được.

## Đọc theo thứ tự

| Tài liệu | Nội dung |
|---|---|
| [docs/setup-guide.md](docs/setup-guide.md) | **Cài đặt từng bước**: AWS, web, Pi, mock ESP32, nạp firmware |
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | Mục tiêu, phạm vi, mốc và phân công 4 người |
| [docs/architecture.md](docs/architecture.md) | Kiến trúc đầu cuối, phần mềm trên AWS, dữ liệu và quyết định thiết kế |
| [docs/parking-layout.md](docs/parking-layout.md) | Sơ đồ hai làn, hai tầng, 18 ô và đường đi |
| [docs/use-cases.md](docs/use-cases.md) | 10 kịch bản chi tiết: vào/ra, email, tính phí, lỗi, lưu 10 ngày |
| [docs/mqtt-contract.md](docs/mqtt-contract.md) | Topic và JSON giữa Pi, ESP32, AWS |
| [docs/api-contract.md](docs/api-contract.md) | API web khách/kiosk/quản trị và mô hình dữ liệu |
| [docs/hardware-and-budget.md](docs/hardware-and-budget.md) | Linh kiện, đấu nối và giá tham khảo |
| [docs/aws-deployment.md](docs/aws-deployment.md) | Tài nguyên AWS và thứ tự triển khai |
| [docs/simulation-and-test-plan.md](docs/simulation-and-test-plan.md) | Mô phỏng 18 nút và nghiệm thu đầu cuối |

DOCX gốc nằm tại thư mục gốc để tham khảo định hướng ban đầu. Tài liệu Markdown trên là thiết kế MVP đã cập nhật theo phạm vi phần cứng hiện tại; các số liệu Free Tier trong DOCX không dùng làm cam kết chi phí.

## Luồng chính

1. Pi thấy **có xe ở làn vào** → backend đánh biển demo (`11111`, `22222`… số nhỏ nhất chưa dùng) → trang **Phiên đỗ** hiện "Chờ cho vào".
2. Quản trị bấm **Cho vào** → servo mở cần vào, xe vào **danh sách xe trong bãi** (hiện ở web Tổng quan và trang camera Pi).
3. OLED hiện ô trống gợi ý; kiosk hiện **QR của phiên** kèm bản đồ. Khách quét QR, **chọn ô trống**, xem **đường đi vẽ từ cổng vào** (ô tầng 2 có bước lên ram), có thể nhập email (tùy chọn **ghi nhớ email cho biển số** để lần sau tự gửi). Ô chỉ để chỉ đường, không gán cho xe.
4. Pi thấy **có xe ở làn ra** → backend chọn xe số lớn nhất, khóa phí demo → trang Phiên đỗ hiện "Chờ cho ra" + phí.
5. Quản trị bấm **Cho ra** (thu tiền trước nếu có phí) → servo mở cần ra, xe rời danh sách, phiên đóng.
6. Dữ liệu định danh (biển số, email lượt) không lưu quá 10 ngày; email đã ghi nhớ giữ tới khi khách hủy liên kết.

## Cấu trúc repository

```text
docs/                       tài liệu hệ thống và hợp đồng
edge/raspberry-pi-vision/   camera, phát hiện xe trong làn, trang xem camera
firmware/esp32-gates/       1 servo cần chắn 3 vị trí, OLED (ESP32-S3)
firmware/esp32-slot-sensors/ 18 nút bấm nối GPIO (ESP32 thường)
backend/src/                Lambda Python: IoT handler, API, job giám sát/purge
backend/tests/              kiểm thử nghiệp vụ với DynamoDB giả (moto)
web/                        một app cho guest/kiosk/admin
simulation/                 mock gate-01/slots-01 + kiểm thử đầu cuối trên AWS
infra/aws/                  template CloudFormation + script deploy/cấp cert/xóa
```

## Nguyên tắc triển khai

- Thống nhất schema v1 ở [MQTT](docs/mqtt-contract.md) và [API](docs/api-contract.md) trước khi viết firmware/backend.
- Dựng mock thiết bị để web/backend chạy được khi chưa có sa bàn.
- Không commit private key/certificate, AWS secret hoặc dữ liệu khách thật.
- Web không điều khiển ESP trực tiếp; backend kiểm tra nghiệp vụ rồi mới phát lệnh.
- Giữ tính phí ở chế độ mô phỏng và xác nhận thu tiền thủ công; không tự nhận là đã thanh toán online.
