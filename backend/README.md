# Backend nghiệp vụ

AWS Lambda nhận sự kiện IoT Core và API web, quản lý phiên/ô, tạo QR token, gán ô bằng ghi có điều kiện, tính phí mô phỏng, phát lệnh cần và gọi Amazon SES. Dữ liệu ở DynamoDB. Xem [kiến trúc](../docs/architecture.md), [use case](../docs/use-cases.md), [API](../docs/api-contract.md).

Backend là nơi duy nhất phát lệnh servo, không coi ACK mở cần là xác nhận xe qua cổng. Email chỉ thuộc lượt hiện tại; không lập bảng liên kết biển số→email lâu dài. Mọi sự kiện/lệnh/API mutation xử lý retry an toàn bằng ID.
