# Hạ tầng AWS

Thiết kế ở [docs/aws-deployment.md](../../docs/aws-deployment.md). [`template.yaml`](template.yaml) (AWS SAM) tạo:

- 6 bảng DynamoDB; Lambda `ingest` (IoT Rule), `api` (HTTP API stage `v1`), `jobs` (EventBridge Scheduler: hết hạn giữ ô và đếm thiết bị offline mỗi phút, xóa dữ liệu định danh mỗi giờ); log giữ 7 ngày;
- Cognito user pool với nhóm `ADMIN`, `KIOSK`; JWT authorizer cho `/kiosk/*`, `/admin/*`; app client cho phép `USER_PASSWORD_AUTH` vì web gọi thẳng API Cognito (`web/src/auth.ts`);
- Thing và IoT policy cho `pi-01`, `gate-01`, `slots-01`, mỗi policy chỉ được topic của thiết bị đó;
- web: S3 riêng tư + CloudFront (OAC, HTTPS, function trả `index.html` cho route của app, header bảo mật để token QR không lọt qua Referer);
- alarm: `jobs` lỗi (purge có thể trễ hạn), `ingest` lỗi (gồm không phát được lệnh cổng), API trả 5xx, thiết bị offline quá 2 phút (báo cả lúc kết nối lại), SES từ chối gửi email chỉ dẫn; hai alarm sau đọc metric `SmartParking/<Stage>` lấy từ log JSON bằng metric filter. Gửi email qua SNS nếu đặt `AlarmEmail`.

Link QR và CORS tự dùng domain CloudFront của stack; đặt `WebBaseUrl` chỉ khi web chạy ở nơi khác. Chưa có trong template: AWS Budgets (đặt trên console). Certificate thiết bị tạo bằng script để private key không đi qua CloudFormation.

Tài khoản nhóm chỉ cho dùng **ap-southeast-2** ([samconfig.toml](samconfig.toml)). Không commit private key, access key, email khách hay ảnh/biển số thật.

## Kiểm tra offline (không cần tài khoản)

```bash
uvx cfn-lint infra/aws/template.yaml
uvx --from shellcheck-py shellcheck infra/aws/scripts/*.sh
cd backend && uv run pytest
```

## Deploy (người 4 tự chạy)

Cần AWS CLI và SAM CLI (`uv tool install aws-sam-cli`). Đăng nhập: `aws login --profile <tên>` rồi `export AWS_PROFILE=<tên>`. Hai script trong [`scripts/`](scripts) mặc định chỉ in lệnh; thêm `--apply` để chạy thật.

1. **Budgets:** đặt cảnh báo 5 USD và 10 USD trên console trước khi tạo tài nguyên.
2. **Khóa ký QR** (SecureString, không đưa vào template):
   ```bash
   aws ssm put-parameter --region ap-southeast-2 --type SecureString \
     --name /smart-parking/dev/claim-keys --value "$(openssl rand -base64 48 | tr -d '\n')"
   ```
   Đổi khóa: đặt giá trị `khóa_mới,khóa_cũ`, sau ít nhất 20 phút đặt lại chỉ `khóa_mới`.
3. **SES sandbox:** xác minh địa chỉ gửi và email từng thành viên (mỗi địa chỉ nhận một thư xác nhận):
   ```bash
   aws sesv2 create-email-identity --region ap-southeast-2 --email-identity <email>
   ```
4. **Build và deploy:**
   ```bash
   cd infra/aws
   sam build
   sam deploy --parameter-overrides SesSender=<email-đã-xác-minh> AlarmEmail=<email-nhận-cảnh-báo>
   ```
   Bấm link xác nhận trong thư SNS để nhận alarm. Output `ApiUrl` gửi cho nhóm để điền `VITE_API_BASE_URL`; `WebUrl` là địa chỉ web. Thêm origin cho web chạy local bằng `CorsOrigins=http://localhost:5173,http://<ip-lan>:5173`.
5. **Web lên CloudFront:**
   ```bash
   infra/aws/scripts/deploy-web.sh            # xem lệnh
   infra/aws/scripts/deploy-web.sh --apply    # build web với ApiUrl/Cognito của stack, sync S3, xóa cache index.html
   ```
6. **Tài khoản demo:**
   ```bash
   aws cognito-idp admin-create-user --user-pool-id <UserPoolId> --username <email> --region ap-southeast-2
   aws cognito-idp admin-add-user-to-group --user-pool-id <UserPoolId> --username <email> \
     --group-name ADMIN --region ap-southeast-2     # hoặc KIOSK
   ```
7. **Certificate thiết bị:**
   ```bash
   infra/aws/scripts/device-certs.sh                  # xem lệnh
   infra/aws/scripts/device-certs.sh --apply          # cả 3 thiết bị; hoặc thêm tên, ví dụ gate-01
   ```
   File ở `secrets/devices/<thiết bị>/` (git bỏ qua) kèm `AmazonRootCA1.pem` và `endpoint.txt`. Gửi riêng cho từng người, không qua git. Thiết bị phải dùng client ID đúng tên Thing; mock và thiết bị thật cùng tên không chạy song song được.
8. **Thử nhanh:** AWS IoT → MQTT test client, subscribe `parking/v1/site-01/#`, publish một `slots_snapshot` đủ 18 ô lên `parking/v1/site-01/slots/slots-01/state` rồi một `vehicle_detected`. Phải thấy `gate_command` và `display_command`; log ở CloudWatch `/aws/lambda/smart-parking-dev-ingest`.
9. **Thử alarm** (CloudWatch → Alarms, lọc `smart-parking-dev`; metric mới chỉ xuất hiện sau lần job/API đầu tiên ghi log):
   - `devices-offline`: tắt mock/thiết bị khoảng 4 phút (90 giây timeout + 2 phút alarm) → thư ALARM; bật lại → thư OK. Khi không chạy thiết bị nào, alarm nằm ở ALARM (chỉ gửi một thư lúc chuyển trạng thái).
   - `email-failed`: SES còn sandbox nên nhập ở trang khách một email **chưa xác minh** → khách vẫn thấy lộ trình, trong vòng 5 phút có thư ALARM; log `email_failed` ở `/aws/lambda/smart-parking-dev-api` cho biết lỗi.

Gỡ toàn bộ sau demo: xóa hết object trong bucket web (`aws s3 rm s3://<WebBucketName> --recursive`), rồi `sam delete --stack-name smart-parking-dev`, xóa certificate và SSM parameter.
