# Backend nghiệp vụ

AWS Lambda nhận sự kiện IoT Core và API web, quản lý phiên/ô, tạo QR token, gán ô bằng ghi có điều kiện, tính phí mô phỏng, phát lệnh cần và gọi Amazon SES. Dữ liệu ở DynamoDB. Xem [kiến trúc](../docs/architecture.md), [use case](../docs/use-cases.md), [API](../docs/api-contract.md).

Backend là nơi duy nhất phát lệnh servo, không coi ACK mở cần là xác nhận xe qua cổng. Email chỉ thuộc lượt hiện tại; không lập bảng liên kết biển số→email lâu dài. Mọi sự kiện/lệnh/API mutation xử lý retry an toàn bằng ID.

Python 3.12, chỉ dùng boto3 có sẵn trong runtime Lambda. Hạ tầng và cách deploy: [infra/aws](../infra/aws/README.md).

## Chạy test

```bash
cd backend
uv sync              # tạo .venv với boto3, moto, pytest
uv run pytest        # DynamoDB giả bằng moto, không cần tài khoản AWS
```

## Cấu trúc `src/parking/`

| File | Vai trò |
|---|---|
| `ingest.py` | Lambda nhận MQTT qua IoT Rule: xe vào/ra, trạng thái ô, ACK cổng/OLED, trạng thái thiết bị |
| `api.py` | Lambda HTTP API: `/public/*`, `/kiosk/active-claims`, `/admin/dashboard` |
| `contract.py` | Kiểm message MQTT v1 và tạo `gate_command`/`display_command` |
| `store.py` | DynamoDB: chuyển kiểu, ghi có điều kiện, transaction |
| `state.py` | Trạng thái ô/thiết bị suy ra lúc đọc |
| `claims.py` | Token QR ký HMAC, cache khóa từ SSM |
| `layout.py`, `pricing.py`, `plates.py` | 18 ô và lộ trình, bảng giá, chuẩn hóa biển số |
| `app.py`, `config.py` | Ghép boto3/IoT/SES và đọc biến môi trường |

## Quyết định thiết kế

- **Gán ô nguyên tử:** một `TransactWriteItems` gồm dấu `event_id`, khóa biển số trong `ActivePlates`, kiểm snapshot ô còn mới, giữ ô `occupied=false`, tạo phiên và ghi `command_id`. Ô vừa bị lượt khác giữ thì thử ô kế tiếp. Lệnh MQTT chỉ phát sau khi transaction thành công; retry gặp `DUPLICATE` nên không mở cần lần hai.
- **Trạng thái suy ra lúc đọc:** ô `UNKNOWN` khi `slots-01` không gửi snapshot quá 90 giây, thiết bị `OFFLINE` khi quá 90 giây không có tin. Không cần job định kỳ cho hai việc này.
- **Không mở cần khi không chắc:** sai làn, không đọc được biển số, confidence < 0,85, biển số đang có phiên, ô không có dữ liệu mới, hoặc sự kiện Pi cũ hơn 60 giây đều tạo phiên `MANUAL_REVIEW` và hiện `CHO NHAN VIEN` trên OLED.
- **Xe ra:** khóa `charge_end_at` và `fee_vnd` ngay khi Pi báo thẻ đỏ; mở cần ra là thao tác quản trị (G3 chưa chốt).
- **QR:** token `session_id.nonce.hạn.chữ_ký`, không lưu trong DB. Kiosk ký lại URL từ dữ liệu phiên. Khóa ở SSM SecureString, cache 5 phút; đổi khóa bằng giá trị `khóa_mới,khóa_cũ`.
- **Email:** một lần mỗi phiên bằng conditional update; retry cùng `Idempotency-Key` trả 202 mà không gửi lại. SES lỗi chỉ ghi `FAILED`, không ảnh hưởng phiên.
- **Dữ liệu định danh:** phiên có `identity_expires_at` (10 ngày) và `purge_due_at` (sớm hơn 1 giờ) trên index thưa `purge_due`. Log không chứa biển số, email, token.

## Khác hoặc bổ sung so với hợp đồng hiện tại

Cần đưa vào PR hợp đồng v1.1 để nhóm duyệt:

1. `GET /kiosk/active-claims` thêm `route_steps`, `created_at`; sắp phiên mới nhất trước.
2. Lỗi 500 trả body chuẩn với mã mới `INTERNAL_ERROR`.
3. Thêm `payment_status=PENDING`. Phiên 0 ₫ sang `EXIT_REQUESTED`, có phí sang `PAYMENT_PENDING`.
4. `review_reason` của `MANUAL_REVIEW`: `WRONG_LANE`, `STALE_EVENT`, `UNREADABLE_PLATE`, `LOW_CONFIDENCE`, `PLATE_ALREADY_ACTIVE`, `SLOTS_UNKNOWN`, `NO_ACTIVE_SESSION`, `SESSION_NOT_PARKED`.
5. `gate_telemetry`/`display_telemetry` phải có phần đầu chung `schema_version`, `message_type`, `event_id`, `device_id`, `occurred_at`; `boot_id`/`seq` không bắt buộc.
6. `GET /public/layout`: `updated_at` là `null` nếu ô chưa từng có dữ liệu.
7. `POST /public/claims/{token}/email` bắt buộc header `Idempotency-Key` (8–64 ký tự `A-Z a-z 0-9 _ -`).
8. Sự kiện Pi cũ hơn 60 giây hoặc lệch giờ quá 30 giây không mở cần.

## Chưa làm

- **Đợt 2:** endpoint quản trị còn lại (danh sách/chi tiết phiên, `resolve-plate`, `renew-claim`, `payment`, `open-exit`, `confirm-passage`, thiết bị, bảng giá) và Idempotency-Key cho các mutation này.
- **Đợt 3:** job theo lịch (giải phóng ô giữ quá 5 phút, purge 10 ngày), alarm CloudWatch, S3 + CloudFront cho web, script tạo certificate thiết bị, chạy API local cho web.
