# Smart Parking — mô hình bãi đỗ xe thông minh

Đồ án kết hợp Raspberry Pi 5, camera, ESP32, cảm biến ô đỗ và AWS để nhận biết xe vào/ra, cập nhật chỗ trống, gợi ý vị trí đỗ và thông báo cho khách.

## Tài liệu

- [Kế hoạch dự án và kiến trúc](PROJECT_PLAN.md)
- [Hợp đồng MQTT/API giữa các module](docs/mqtt-contract.md)
- [Mô phỏng và kiểm thử tích hợp](docs/simulation-and-test-plan.md)

## Bắt đầu

1. Cả nhóm thống nhất sơ đồ bãi, topic MQTT và JSON schema trong `docs/`.
2. Chạy mock thiết bị trước để kiểm tra luồng nghiệp vụ mà chưa cần phần cứng.
3. Phát triển từng module trong `edge/`, `firmware/`, `backend/` và `web/`.
4. Tích hợp AWS IoT Core sau khi luồng MQTT local chạy ổn định.

## Khung thư mục

```text
docs/                  tài liệu kiến trúc, giao thức, mô phỏng
edge/                  Raspberry Pi 5, camera, nhận diện
firmware/esp32-gates/  firmware hai cần chắn
firmware/esp32-slot-sensors/ firmware cảm biến ô đỗ
backend/               API, nghiệp vụ, thông báo
web/                   dashboard
simulation/            mock device, mô hình bãi, kịch bản
infra/aws/              cấu hình hạ tầng AWS
```

## Nguyên tắc làm việc

- Không commit credential, private key, certificate thiết bị hoặc thông tin khách.
- Tách cấu hình local/simulation khỏi cấu hình AWS.
- Mọi message có `event_id` hoặc `command_id`; mọi module xử lý lặp an toàn.
- Chỉ backend ra quyết định gán ô và phát lệnh cần chắn; firmware kiểm tra timeout và giới hạn an toàn tại chỗ.

## Tài liệu nền

Đọc [PROJECT_PLAN.md](PROJECT_PLAN.md) để biết phạm vi MVP, luồng vào/ra, kết nối SES/SNS, gán ô và phân công nhóm.
