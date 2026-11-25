# Backend nghiệp vụ

AWS Lambda nhận sự kiện IoT Core và API web, quản lý phiên (chờ vào → trong bãi → chờ ra → đóng, quản trị cho phép từng bước), đánh biển số demo, gợi ý ô trống, tạo QR token, tính phí mô phỏng, phát lệnh cần, gửi danh sách xe cho Pi và gọi Amazon SES. Dữ liệu ở DynamoDB. Xem [kiến trúc](../docs/architecture.md), [use case](../docs/use-cases.md), [API](../docs/api-contract.md).

Backend là nơi duy nhất phát lệnh servo, không coi ACK mở cần là xác nhận xe qua cổng. Email mặc định chỉ thuộc lượt hiện tại; chỉ khi khách tự tích "ghi nhớ" mới lưu liên kết biển số→email (bảng `PlateEmails`, hủy bằng link trong email). Mọi sự kiện/lệnh/API mutation xử lý retry an toàn bằng ID.

## Mã nguồn

| File | Vai trò |
|---|---|
| `src/iot_handler.py` | Lambda nhận message thiết bị từ IoT Rule, định tuyến theo topic |
| `src/api_handler.py` | Lambda cho HTTP API: public/guest/kiosk/admin, kiểm nhóm Cognito, Idempotency-Key |
| `src/jobs.py` | Mỗi phút: thiết bị offline, ô UNKNOWN, giữ ô quá 5 phút, lệnh chưa ACK. Mỗi giờ: purge định danh. `seed` lúc deploy |
| `src/logic.py` | Nghiệp vụ: biển demo, chờ vào/cho vào (`TransactWriteItems`), chờ ra/cho ra, phí, gợi ý ô, danh sách xe (`lot_state`), tự gửi email theo biển |
| `src/services.py` | Token QR HMAC, bảng giá, publish lệnh qua IoT Data Plane, email SES |
| `src/core.py` | Bảng DynamoDB, thời gian, ID, layout 18 ô, cảnh báo, chống trùng |

Chỉ dùng `boto3` có sẵn trong runtime Lambda, không cần build. Deploy: [infra/aws](../infra/aws/README.md).

```bash
pip install "moto[dynamodb]" boto3 pytest
cd backend && python -m pytest -q        # 11 kịch bản: vào/ra, phí, replay, đầy, tranh ô, offline, email, quyền
```
