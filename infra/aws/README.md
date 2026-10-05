# Hạ tầng AWS

Tài liệu triển khai ở [docs/aws-deployment.md](../../docs/aws-deployment.md). MVP dùng IoT Core, Lambda/API Gateway, DynamoDB, SES, Cognito, S3/CloudFront, EventBridge Scheduler, CloudWatch và Budgets. Chưa có template IaC trong thư mục này.

Thiết bị có certificate/policy riêng; backend dùng IAM role. Không commit private key, access key, email khách hay ảnh/biển số thật. Cấu hình cảnh báo chi phí trước khi chạy demo.
