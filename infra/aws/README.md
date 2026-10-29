# Hạ tầng AWS

Thiết kế ở [docs/aws-deployment.md](../../docs/aws-deployment.md). [`template.yaml`](template.yaml) (AWS SAM) tạo:

- 6 bảng DynamoDB, Lambda `ingest` (IoT Rule) và `api` (HTTP API stage `v1`), log giữ 7 ngày;
- Cognito user pool với nhóm `ADMIN`, `KIOSK`; JWT authorizer cho `/kiosk/*`, `/admin/*`;
- Thing và IoT policy cho `pi-01`, `gate-01`, `slots-01`, mỗi policy chỉ được topic của thiết bị đó.

Chưa có trong template: S3/CloudFront cho web, EventBridge Scheduler (purge, hết hạn giữ ô), alarm, Budgets. Certificate thiết bị tạo bằng CLI để private key không đi qua CloudFormation.

Tài khoản nhóm chỉ cho dùng **ap-southeast-2** ([samconfig.toml](samconfig.toml)). Không commit private key, access key, email khách hay ảnh/biển số thật.

## Kiểm tra offline (không cần tài khoản)

```bash
uvx cfn-lint infra/aws/template.yaml
cd backend && uv run pytest
```

## Deploy (người 4 tự chạy)

Cần AWS CLI và SAM CLI (`uv tool install aws-sam-cli`). Đăng nhập: `aws login --profile <tên>` rồi `export AWS_PROFILE=<tên>`.

1. **Budgets:** đặt cảnh báo 5 USD và 10 USD trên console trước khi tạo tài nguyên.
2. **Khóa ký QR** (SecureString, không đưa vào template):
   ```bash
   aws ssm put-parameter --region ap-southeast-2 --type SecureString \
     --name /smart-parking/dev/claim-keys --value "$(openssl rand -base64 48 | tr -d '\n')"
   ```
3. **SES sandbox:** xác minh địa chỉ gửi và email từng thành viên (mỗi địa chỉ nhận một thư xác nhận):
   ```bash
   aws sesv2 create-email-identity --region ap-southeast-2 --email-identity <email>
   ```
4. **Build và deploy:**
   ```bash
   cd infra/aws
   sam build
   sam deploy --parameter-overrides SesSender=<email-đã-xác-minh> \
     WebBaseUrl=http://localhost:5173 CorsOrigins=http://localhost:5173
   ```
   Output `ApiUrl` gửi cho nhóm để điền `VITE_API_BASE_URL`. Khi có CloudFront, deploy lại với `WebBaseUrl` và `CorsOrigins` là domain web.
5. **Tài khoản demo:**
   ```bash
   aws cognito-idp admin-create-user --user-pool-id <UserPoolId> --username <email> --region ap-southeast-2
   aws cognito-idp admin-add-user-to-group --user-pool-id <UserPoolId> --username <email> \
     --group-name ADMIN --region ap-southeast-2     # hoặc KIOSK
   ```
6. **Certificate thiết bị** (lặp cho `pi-01`, `gate-01`, `slots-01`; policy tên `smart-parking-dev-<thiết bị>`):
   ```bash
   aws iot create-keys-and-certificate --set-as-active --region ap-southeast-2 \
     --certificate-pem-outfile pi-01.cert.pem --private-key-outfile pi-01.private.key
   aws iot attach-policy --policy-name smart-parking-dev-pi-01 --target <certificateArn> --region ap-southeast-2
   aws iot attach-thing-principal --thing-name pi-01 --principal <certificateArn> --region ap-southeast-2
   aws iot describe-endpoint --endpoint-type iot:Data-ATS --region ap-southeast-2
   ```
   Gửi riêng cho từng người (không qua git): file cert, private key, `AmazonRootCA1.pem` và endpoint ATS. Thiết bị phải dùng client ID đúng tên Thing; mock và thiết bị thật cùng tên không chạy song song được.
7. **Thử nhanh:** AWS IoT → MQTT test client, subscribe `parking/v1/site-01/#`, publish một `slots_snapshot` đủ 18 ô lên `parking/v1/site-01/slots/slots-01/state` rồi một `vehicle_detected`. Phải thấy `gate_command` và `display_command`; log ở CloudWatch `/aws/lambda/smart-parking-dev-ingest`.

Gỡ toàn bộ sau demo: `sam delete --stack-name smart-parking-dev`, xóa certificate và SSM parameter.
