# AWS development environment

Môi trường dev dự kiến gồm AWS IoT Core, IoT Rules, backend (Lambda/API hoặc dịch vụ tương đương), database và Amazon SES. Chỉ bật SMS SNS sau khi kiểm tra khả năng gửi đến quốc gia đích và dự toán chi phí.

Không commit certificate/private key hoặc access key. Dùng IAM role cho backend; policy IoT giới hạn topic theo từng thiết bị; tách dev/prod và đặt budget cảnh báo.
