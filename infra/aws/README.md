# Hạ tầng AWS

Toàn bộ tài nguyên khai báo trong [template.yaml](template.yaml) (CloudFormation kèm SAM). Chỉ cần AWS CLI v2 để triển khai. Hướng dẫn từng bước: [docs/setup-guide.md](../../docs/setup-guide.md).

| Script | Làm gì |
|---|---|
| `deploy.sh` | Đóng gói Lambda, dựng hoặc cập nhật stack, tạo 18 ô và bảng giá, ghi cấu hình cho web |
| `create-users.sh` | Tạo hoặc đặt lại mật khẩu cho tài khoản `admin` và `kiosk` |
| `provision-devices.sh` | Tạo 3 thiết bị trên IoT Core kèm chứng chỉ và quyền; sinh `config.local.toml` cho Pi và `secrets.h` cho ESP32. Chạy kèm `WIFI_SSID=... WIFI_PASS=...` |
| `deploy-web.sh` | Build web, đưa lên S3, làm mới CloudFront |
| `setup-pi.sh` | Từ laptop: lấy mã nguồn về Pi, chép chứng chỉ, cài và bật `pi-vision` |
| `copy-pi-certs.sh` | Chép chứng chỉ của Pi qua SSH (`setup-pi.sh` đã gọi sẵn) |
| `destroy.sh` | Xóa toàn bộ: stack, thiết bị IoT, chứng chỉ |

Biến môi trường có thể đặt trước lệnh:

- `AWS_REGION`: mặc định `ap-southeast-1`.
- `STAGE`: mặc định `dev`.
- `ENABLE_CDN=false`: khi tài khoản chưa dùng được CloudFront.
- `WEB_BASE_URL_OVERRIDE`: để mã QR trỏ về web chạy trên laptop.
- `IOT_PORT=443`: khi mạng chặn cổng 8883.

Tài nguyên được tạo: 8 bảng DynamoDB, 3 Lambda (log giữ 7 ngày), 1 IoT Rule, HTTP API có kiểm tra đăng nhập Cognito, địa chỉ email SES, S3 + CloudFront, lịch EventBridge, AWS Budgets. Email, khóa ký QR và chứng chỉ nằm trong `secrets/`, không commit.
