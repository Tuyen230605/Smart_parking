# Smart Parking

Đồ án môn Điện toán đám mây (INT3319E_2): hệ thống bãi đỗ xe thông minh trên AWS, chạy trên một sa bàn 2 tầng, 18 ô.

## Hệ thống làm gì

1. Camera trên Raspberry Pi thấy có xe ở làn vào. Trang quản trị hiện "Chờ cho vào" kèm biển số demo (11111, 22222, ...).
2. Nhân viên bấm *Cho vào*. Cần chắn (ESP32-S3 + servo) quay sang trái rồi tự đóng.
3. Màn hình ở cổng hiện mã QR. Khách quét để xem ô trống gần nhất và đường đi trên bản đồ, có thể nhận hướng dẫn qua email.
4. Camera thấy xe ở làn ra. Hệ thống tính tiền theo thời gian đỗ.
5. Nhân viên thu tiền, bấm *Cho ra*. Cần quay sang phải, xe rời danh sách.

18 nút nhấn trên sa bàn (nối vào một ESP32) giả lập cảm biến có xe ở từng ô, dùng để biết ô nào còn trống.

## Thành phần

| Thư mục | Nội dung |
|---|---|
| `infra/aws/` | Template CloudFormation và các script dựng hạ tầng bằng AWS CLI |
| `backend/` | Mã Python cho 3 hàm Lambda, kèm kiểm thử |
| `web/` | Ứng dụng React: sơ đồ bãi, kiosk QR, trang khách, trang quản trị |
| `edge/raspberry-pi-vision/` | Chương trình phát hiện xe trên Pi và trang camera |
| `firmware/esp32-gates/` | ESP32-S3 điều khiển cần chắn |
| `firmware/esp32-slot-sensors/` | ESP32 đọc 18 nút |
| `simulation/` | Chương trình giả lập thiết bị khi chưa có phần cứng |
| `docs/` | Tài liệu thiết kế và hướng dẫn |
| `report/` | Báo cáo LaTeX |

## Đọc tài liệu theo thứ tự

1. [docs/setup-guide.md](docs/setup-guide.md): cài đặt từ đầu đến cuối.
2. [docs/architecture.md](docs/architecture.md): kiến trúc và luồng xử lý.
3. [docs/use-cases.md](docs/use-cases.md): các tình huống sử dụng.
4. [docs/mqtt-contract.md](docs/mqtt-contract.md) và [docs/api-contract.md](docs/api-contract.md): định dạng tin nhắn giữa thiết bị, web và đám mây.
5. [docs/parking-layout.md](docs/parking-layout.md): sơ đồ 18 ô và bảng chân nút.
6. [docs/hardware-and-budget.md](docs/hardware-and-budget.md), [docs/aws-deployment.md](docs/aws-deployment.md), [docs/simulation-and-test-plan.md](docs/simulation-and-test-plan.md), [docs/team-tasks.md](docs/team-tasks.md).

## Lệnh nhanh

```bash
cd infra/aws
./deploy.sh              # dựng hạ tầng AWS
./create-users.sh        # tài khoản admin, kiosk
WIFI_SSID=... WIFI_PASS=... ./provision-devices.sh   # chứng chỉ cho 3 thiết bị
./deploy-web.sh          # đưa web lên CloudFront
./setup-pi.sh oi@<ip-pi> # cài chương trình lên Pi
```

Kiểm thử: `cd backend && ../.venv/bin/python -m pytest -q tests`.

Không commit khóa, chứng chỉ hay mật khẩu Wi-Fi. Các tệp này nằm trong `secrets/`, `*.local.*` và `include/secrets.h`, đã có trong `.gitignore`.
