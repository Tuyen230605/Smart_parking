# AWS: tài nguyên, quyền và thứ tự dựng

Tài liệu chuẩn bị môi trường dev. Đây là thiết kế, chưa triển khai tài nguyên AWS. Chọn một region có AWS IoT Core, SES và các dịch vụ cần dùng; dùng cùng region cho IoT/backend/DB/SES để đơn giản và kiểm tra giá tại [AWS Pricing Calculator](https://calculator.aws/).

## 1. Tài nguyên MVP

| Dịch vụ | Tài nguyên | Vai trò |
|---|---|---|
| AWS IoT Core | 3 Things/certificates/policies: `pi-01`, `gate-01`, `slots-01` | MQTT/TLS và phân quyền topic |
| IoT Rules | Rule riêng cho vision, slots, gate/display telemetry, status | Đưa sự kiện đến Lambda xử lý |
| AWS Lambda | Handler sự kiện, HTTP API, purge định danh | Gán ô, phiên đỗ, giá, QR, SES |
| Amazon API Gateway HTTP API | Route public/guest/kiosk/admin | HTTPS cho web |
| Amazon DynamoDB | Slots, Sessions, ActivePlates, ProcessedMessages, DeviceStatus, PricingConfig | Dữ liệu hiện thời và nghiệp vụ |
| Amazon SES | Sender identity, email template | Gửi chỉ dẫn theo lượt |
| Amazon S3 + CloudFront | Web tĩnh và HTTPS | Một app responsive cho khách/kiosk/admin |
| Amazon Cognito | User pool, nhóm `ADMIN`/`KIOSK` | Đăng nhập và JWT |
| Amazon EventBridge Scheduler | Lịch chạy purge mỗi giờ | Dọn định danh trước hạn 10 ngày |
| Amazon CloudWatch | Logs/alarms | Lỗi, thiết bị offline, SES failure |
| AWS Budgets | Email cảnh báo chi phí | Kiểm soát chi phí đồ án |

Không cần RDS, SQS, Rekognition hoặc SNS SMS cho MVP. Nếu Pi OCR không đủ tốt, đánh giá Rekognition như một phương án sau với chi phí và thay đổi luồng ảnh rõ ràng.

## 2. Thứ tự triển khai

1. Chọn region, đặt AWS Budget và quy ước tên `smart-parking-dev-*`.
2. Tạo DynamoDB tables/index/conditional write cho [API/data model](api-contract.md). Cấu hình TTL hỗ trợ dọn rác, EventBridge Scheduler + purge Lambda chạy theo giờ.
3. Tạo IoT Things và certificate **riêng từng thiết bị**; mỗi policy chỉ được publish/sub topic của nó theo [MQTT contract](mqtt-contract.md). Kiểm tra 3 thiết bị có thể kết nối mà không truy cập chéo.
4. Tạo IoT Rules đưa sự kiện vào Lambda. Lambda kiểm tra schema, dedupe event, ghi phiên/ô nguyên tử, publish lệnh qua IoT Data Plane.
5. Tạo API Gateway HTTP API, Cognito groups/JWT authorizer cho admin/kiosk. Guest route dùng token QR, giới hạn thời hạn và gửi email.
6. Xác minh sender SES. Trong sandbox, chỉ gửi tới email đã xác minh của nhóm; nếu muốn nhập email bất kỳ, gửi yêu cầu production access trước khi demo.
7. Build web app lên S3 private, phân phối qua CloudFront với HTTPS. Kiosk mở trang hiển thị QR; OLED chỉ hiện chữ.
8. Bật CloudWatch log retention ngắn, không log biển số/email/token. Kiểm tra cảnh báo chi phí và xóa tài nguyên dev sau đồ án.

## 3. Quyền IAM tối thiểu

- Handler IoT vision/slots: đọc/ghi các bảng cần thiết, không có quyền SES nếu không gửi email.
- Handler API guest email: chỉ đọc phiên theo hash token, cập nhật email/trạng thái gửi và `ses:SendEmail` với sender đã xác minh.
- Handler command: chỉ `iot:Publish` lên gate/display command topics.
- Purge Lambda: quyền quét index hạn và xóa thuộc tính/bản ghi định danh, không cần IoT/SES.
- Firmware: certificate X.509 riêng, policy theo topic. Không nhúng IAM access key/secret vào Pi hoặc ESP.

## 4. Cấu hình cần lưu ngoài repository

`AWS_REGION`, IoT endpoint, tên bảng DynamoDB, SES sender, Cognito IDs, URL frontend/API, ngưỡng OCR, thời hạn token và giá demo. Khóa HMAC ký QR đặt trong cấu hình mã hóa của Lambda/secret store của môi trường, không ở source. File `.env` local, certificate/private key và token không commit. Có thể commit `.env.example` với tên biến nhưng giá trị giả.

## 5. SES và email theo phiên

Sau khi guest submit email, backend tạo email gồm mã phiên rút gọn, ô, tầng và lộ trình. Không gửi biển số đầy đủ. `SendEmail` trả kết quả chấp nhận xử lý; nó **không bảo đảm thư đã đến inbox**. Bật delivery/bounce feedback nếu cần đo tỷ lệ phát thư. Form giới hạn một email mỗi phiên và rate limit; quản trị có thể resend có log.

Tài khoản SES sandbox chỉ gửi tới địa chỉ đã xác minh. [Hướng dẫn xác minh identity](https://docs.aws.amazon.com/ses/latest/dg/verify-addresses-and-domains.html), [xin production access](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html), [API SendEmail](https://docs.aws.amazon.com/ses/latest/dg/send-email-api.html).

## 6. Lưu biển số/email tối đa 10 ngày

- Mỗi thuộc tính định danh có `collected_at`, `purge_due_at = collected_at + 9 days 23 hours` và `identity_expires_at = collected_at + 10 days`.
- API lọc dữ liệu quá hạn ngay lúc đọc; purge Lambda chạy mỗi giờ và xóa các thuộc tính/bản ghi đến hạn, có alarm khi job lỗi. DynamoDB TTL chỉ áp dụng cho item được xóa trọn; không dùng TTL để xóa riêng biển số/email trong phiên cần giữ số liệu phí.
- `ActivePlates` chứa biển số trong khóa; nếu phiên còn mở sát hạn, cảnh báo quản trị để đóng/xử lý trước khi purge. Không giữ khóa định danh này vô hạn.
- Nếu dùng snapshot OCR để debug, chỉ lưu local tạm trong Pi và tự xóa; khi bật S3 phải đặt lifecycle, quyền và lịch purge tương ứng trước khi upload.
- CloudWatch không được ghi raw MQTT payload chứa biển số hoặc email. Cấu hình retention log và redaction.

## 7. Ước lượng chi phí trước demo

Giả sử 1.000 xe vào + 1.000 xe ra/tháng; 500 người nhập email; ESP slots phát 1 snapshot/30 giây ≈ 86.400 snapshot/tháng nếu chạy 24/7, cộng message thay đổi và heartbeat. Đây là **số lượng đầu vào cho Calculator**, không phải dự báo hóa đơn. IoT Core tính riêng connectivity, messaging và Rules; SES tính theo plan/vùng. Xem [giá IoT Core](https://aws.amazon.com/iot-core/pricing/), [giá SES](https://aws.amazon.com/ses/pricing/), [giá DynamoDB](https://aws.amazon.com/dynamodb/pricing/).

Không chép các hạn mức Free Tier trong DOCX gốc vào ngân sách vì chính sách theo thời điểm, vùng và loại tài khoản có thể đổi.
