# Hạ tầng AWS

Các bước dựng hạ tầng nằm ở [setup-guide.md](setup-guide.md). Tài liệu này giải thích hạ tầng gồm những gì, quyền ra sao và dữ liệu được giữ bao lâu.

## Tài nguyên

Tất cả khai báo trong `infra/aws/template.yaml` (CloudFormation kèm SAM), vùng `ap-southeast-1` (Singapore). Tên tài nguyên có tiền tố `smart-parking-dev-`.

| Dịch vụ | Tài nguyên |
|---|---|
| IoT Core | 3 thiết bị `pi-01`, `gate-01`, `slots-01`, mỗi thiết bị một chứng chỉ và một chính sách quyền. Phần này do script `provision-devices.sh` tạo, không nằm trong template, để khóa riêng không đi qua CloudFormation |
| IoT Rule | 1 rule chuyển tin nhắn từ thiết bị sang Lambda `iot` |
| Lambda | `iot`, `api`, `jobs`; Python 3.12, chip ARM, 256 MB |
| DynamoDB | 8 bảng, trả tiền theo mức dùng |
| API Gateway | 1 HTTP API với 19 đường dẫn, kiểm tra đăng nhập bằng Cognito |
| Cognito | 1 user pool, 2 nhóm `ADMIN` và `KIOSK` |
| SES | Địa chỉ email gửi |
| S3 + CloudFront | Kho S3 chặn truy cập công khai, chỉ CloudFront được đọc (OAC) |
| EventBridge | Lịch chạy Lambda `jobs`: mỗi phút (giám sát) và mỗi giờ (dọn dữ liệu) |
| CloudWatch Logs | 3 nhóm log, giữ 7 ngày |
| Budgets | Cảnh báo khi chi phí tháng vượt 5 USD |

## Quyền

- Mỗi thiết bị chỉ kết nối được bằng đúng tên của mình và chỉ gửi, nhận trên đúng kênh của mình. Ví dụ Pi chỉ được gửi sự kiện xe, gửi tin báo còn sống, và nhận danh sách xe. Thiết bị không có khóa truy cập AWS.
- Mỗi hàm Lambda chỉ được dùng các bảng cần thiết. Quyền gửi tin MQTT giới hạn ở kênh lệnh của cổng và kênh danh sách xe của Pi. Quyền gửi email chỉ từ địa chỉ đã xác minh.
- Tài khoản trên web do quản trị tạo, không cho tự đăng ký.

## Thông tin bí mật

Không đưa lên GitHub:
- `secrets/deploy.env`: email, khóa dùng để ký link QR.
- `secrets/certs/`: chứng chỉ và khóa riêng của thiết bị.
- `edge/raspberry-pi-vision/config.local.toml` và `firmware/*/include/secrets.h`: cấu hình kết nối của thiết bị, có Wi-Fi và khóa riêng.
- `web/.env.*.local`: địa chỉ API và thông tin Cognito.

Các tệp này đã có trong `.gitignore`.

## Email

Tài khoản SES mới ở chế độ thử, chỉ gửi được tới địa chỉ đã xác minh. Muốn gửi cho email bất kỳ thì vào SES Console xin quyền dùng thật (thường được duyệt trong khoảng một ngày). Email không chứa biển số. SES nhận yêu cầu gửi không có nghĩa là thư chắc chắn tới hộp thư.

## Giữ dữ liệu cá nhân tối đa 10 ngày

- Biển số và email của mỗi phiên có mốc hết hạn 10 ngày tính từ lúc thu thập.
- Lambda `jobs` chạy mỗi giờ, xóa các dữ liệu đã quá 9 ngày 23 giờ. Phiên còn mở mà sắp hết hạn thì có cảnh báo.
- Bảng tin đã xử lý và bảng cảnh báo tự xóa bản ghi hết hạn (DynamoDB TTL).
- Email khách tự chọn ghi nhớ theo biển số thì giữ tới khi khách hủy.
- Log không ghi biển số, email.

## Gỡ bỏ

```bash
cd infra/aws && ./destroy.sh
```

Script xóa kho web, stack CloudFormation, thiết bị IoT, chứng chỉ và chính sách.
