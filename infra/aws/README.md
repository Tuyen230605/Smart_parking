# Hạ tầng AWS

Toàn bộ tài nguyên nằm trong [template.yaml](template.yaml) (CloudFormation + SAM transform); deploy chỉ cần AWS CLI v2. Hướng dẫn từng bước: [docs/setup-guide.md](../../docs/setup-guide.md).

| Script | Việc |
|---|---|
| `deploy.sh` | Đóng gói Lambda, dựng/cập nhật stack, seed 18 ô + bảng giá, ghi `web/.env.*.local` |
| `create-users.sh` | Tài khoản Cognito `admin` (ADMIN) và `kiosk` (KIOSK) |
| `provision-devices.sh` | 3 IoT Thing + cert + policy theo topic; sinh `config.local.toml` cho Pi và `secrets.h` cho ESP32 |
| `copy-pi-certs.sh` | Chép cert `pi-01` sang Pi qua SSH |
| `deploy-web.sh` | Build web, upload S3, invalidate CloudFront |
| `destroy.sh` | Xóa stack, cert, Thing sau khi xong đồ án |

Biến môi trường: `AWS_REGION` (mặc định `ap-southeast-1`), `STAGE` (`dev`), `ENABLE_CDN=false` khi tài khoản chưa dùng được CloudFront, `WEB_BASE_URL_OVERRIDE` để QR trỏ về web chạy local, `IOT_PORT=443` khi mạng chặn 8883.

Tài nguyên: 7 bảng DynamoDB on-demand, 3 Lambda arm64 (log giữ 7 ngày), 1 IoT Rule, HTTP API + JWT authorizer Cognito, SES identity, S3 private + CloudFront OAC, EventBridge schedule, AWS Budget. Giá trị riêng (email, khóa HMAC QR, cert) nằm trong `secrets/` — không commit.
