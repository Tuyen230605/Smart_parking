# Hợp đồng REST API v1 và mô hình dữ liệu

Base URL: `https://<api-domain>/v1`. Web app dùng HTTPS/JSON. Thiết bị dùng [MQTT](mqtt-contract.md), không gọi các endpoint này. Tất cả thao tác thay đổi có `Idempotency-Key` do client tạo; backend lưu kết quả theo key để retry an toàn.

## 1. Quyền truy cập

| Vai trò | Cách truy cập | Được thấy/làm |
|---|---|---|
| Public | Không đăng nhập | Sơ đồ ô tổng quan; không thấy biển số/email/phí từng xe |
| Guest phiên | URL QR token ngẫu nhiên, hết hạn sau 15 phút | Ô và lộ trình của phiên; có thể gửi một email hướng dẫn |
| Kiosk | Cognito nhóm `KIOSK` | QR phiên mới nhất và ô/lộ trình để hiện tại cổng; không thấy danh sách biển số |
| Admin | Cognito nhóm `ADMIN` | Phiên, phí, thiết bị, xử lý lỗi, xác nhận thu tiền/xe ra |

Backend kiểm tra quyền tại API, không dựa vào việc ẩn nút trên web. Token QR chứa `session_id`, `claim_nonce` ngẫu nhiên ít nhất 128 bit và thời hạn, được ký HMAC; backend kiểm tra chữ ký, nonce hiện hành và hạn 15 phút. Raw token được tạo lại cho kiosk từ dữ liệu phiên, không lưu trong DB. Không đặt email hoặc biển số trong URL.

## 2. Public và guest

### `GET /public/layout`

Trả 18 ô, `source=SENSOR|BUTTON`, trạng thái `AVAILABLE|RESERVED|OCCUPIED|UNKNOWN|OUT_OF_SERVICE` và `updated_at`, không có biển số. Public web có thể poll mỗi 5–10 giây; ô mô phỏng được ghi nhãn rõ.

### `GET /public/claims/{token}`

Trả `session_id` rút gọn, `slot_id`, `route_steps`, `claim_expires_at`, `email_submitted`. Không trả biển số, email đã nhập hay danh sách phiên khác.

```json
{
  "session_ref": "A7K2",
  "slot_id": "F1-A1",
  "route_steps": ["Tầng 1", "Đi đến hàng A", "Ô số 1"],
  "claim_expires_at": "2026-10-05T09:15:00Z",
  "email_submitted": false
}
```

### `POST /public/claims/{token}/email`

```json
{
  "email": "visitor@example.com",
  "consent_for_this_session": true
}
```

Trả `202 Accepted` và `email_status=QUEUED`. Backend dùng conditional update để một request duy nhất chuyển email sang `QUEUED`, sau đó gọi SES; lưu `ACCEPTED_BY_SES|FAILED` theo kết quả API. Chỉ gọi là `DELIVERED` nếu có feedback giao thư. Từ chối khi token hết hạn, thiếu consent, email sai định dạng hoặc đã gửi trước đó; giới hạn tốc độ theo token/IP. Email này chỉ thuộc phiên hiện tại, không gắn vào hồ sơ xe dùng lại.

## 3. Kiosk và admin

| Endpoint | Vai trò | Tác dụng |
|---|---|---|
| `GET /kiosk/active-claims` | KIOSK/ADMIN | Danh sách phiên vào còn token hiệu lực gồm mã rút gọn, ô và URL; frontend chọn phiên để hiện QR lớn |
| `GET /admin/dashboard` | ADMIN | Tổng số ô trống/đang giữ/có xe, thiết bị offline, cảnh báo |
| `GET /admin/sessions?status=...` | ADMIN | Danh sách phiên, phân trang; biển số/email chỉ khi còn hạn lưu |
| `GET /admin/sessions/{id}` | ADMIN | Chi tiết, thời gian, ô, trạng thái phí/lệnh |
| `POST /admin/sessions/{id}/resolve-plate` | ADMIN | Sửa OCR thấp, chọn vào/ra, ghi người thao tác và lý do |
| `POST /admin/sessions/{id}/renew-claim` | ADMIN | Tạo token QR mới nếu khách đến muộn |
| `POST /admin/sessions/{id}/payment` | ADMIN | Ghi `PAID_CASH` hoặc `WAIVED` và lý do |
| `POST /admin/sessions/{id}/open-exit` | ADMIN | Chỉ khi phiên hợp lệ và phí có `NO_CHARGE/PAID_CASH/WAIVED`; phát lệnh cần ra |
| `POST /admin/sessions/{id}/confirm-passage` | ADMIN | Xác nhận xe đã qua, chốt giờ/phí và đóng phiên |
| `GET /admin/devices` | ADMIN | Trạng thái Pi, ESP gate, ESP slots và thời điểm cuối |
| `GET /admin/pricing`, `PUT /admin/pricing` | ADMIN | Xem/sửa bảng giá demo |

Ví dụ gửi xác nhận thu tiền:

```json
{
  "payment_status": "PAID_CASH",
  "amount_vnd": 10000,
  "note": "Đã thu tại cổng"
}
```

Nếu `WAIVED`, `note` bắt buộc. API trả `409 Conflict` nếu trạng thái phiên không cho phép hành động. Mọi hành động admin ghi `actor_id`, `occurred_at`, `reason`.

## 4. Mã lỗi thống nhất

| HTTP | `code` | Tình huống |
|---:|---|---|
| 400 | `INVALID_INPUT` | Email/payload/giá không hợp lệ |
| 401/403 | `UNAUTHENTICATED`/`FORBIDDEN` | Thiếu quyền |
| 404 | `NOT_FOUND` | Không có phiên/token |
| 409 | `SLOT_CONFLICT`, `INVALID_STATE`, `EMAIL_ALREADY_SENT` | Ô bị giữ, trạng thái sai, gửi trùng |
| 410 | `TOKEN_EXPIRED` | QR hết hạn |
| 429 | `RATE_LIMITED` | Gọi quá nhanh |
| 503 | `DEVICE_OFFLINE` | Không thể điều khiển cổng an toàn |

Body lỗi:

```json
{"code":"TOKEN_EXPIRED","message":"Mã QR đã hết hạn","request_id":"uuid"}
```

## 5. Lưu trữ và ràng buộc

### `Slots`

`slot_id` (PK), `floor`, `row`, `column`, `source`, `occupied`, `status`, `reserved_session_id`, `sensor_seen_at`, `updated_at`. Gán ô bằng DynamoDB conditional write: chỉ từ `AVAILABLE` sang `RESERVED` khi dữ liệu mới và không có `reserved_session_id`. Retry ô tiếp theo nếu conflict. Backend kiểm tra `source` đúng map F1-A1/17 nút.

### `Sessions`

`session_id` (PK), `plate_normalized`, `plate_collected_at`, `checkin_at`, `charge_end_at`, `exit_confirmed_at`, `slot_id`, `state`, `claim_nonce`, `claim_expires_at`, `email`, `email_collected_at`, `email_status`, `payment_status`, `fee_vnd`, `identity_expires_at`.

### `ActivePlates` và thao tác tạo phiên

`plate_normalized` (PK), `session_id`. Một `TransactWriteItems` gồm: giữ ô `AVAILABLE → RESERVED` có điều kiện, tạo Session chưa tồn tại, tạo ActivePlates chưa tồn tại và ghi `event_id` đã xử lý. Nếu hai xe tranh ô hoặc cùng biển số, transaction chỉ cho một lượt thành công; backend thử ô khác khi **chỉ** có slot conflict. Khi đóng phiên, xóa ActivePlates có điều kiện đúng `session_id`. GSI thuần túy không bảo đảm uniqueness.

### `ProcessedMessages` và `DeviceStatus`

`event_id` hoặc `command_id` (PK), loại và thời điểm xử lý để dedupe. `device_id` → `last_seen_at`, `state`, `firmware_version`. Idempotency key API được lưu cùng kết quả trong một khoảng đủ cho retry.

### `PricingConfig`

Phiên bản bảng giá, mốc thời gian hiệu lực, miễn phí dưới 15 phút, 10.000 ₫ đến hết 60 phút, 5.000 ₫ cho mỗi giờ tiếp theo bắt đầu. Ví dụ: 61 phút = 15.000 ₫. Phiên lưu phiên bản giá khi check-in để không đổi giá giữa chừng. `charge_end_at` được khóa khi yêu cầu ra; `exit_confirmed_at` chỉ xác nhận xe đã qua. Phí 0 ₫ có `payment_status=NO_CHARGE`.

## 6. Thời hạn dữ liệu

`identity_expires_at` tối đa 10 ngày sau lúc thu thập từng loại định danh. API từ chối trả biển số/email/token đã quá hạn; job purge theo giờ xóa từ mốc 9 ngày 23 giờ và cảnh báo nếu lỗi. DynamoDB TTL chỉ dùng cho item có thể xóa toàn bộ; Lambda xóa thuộc tính định danh khỏi phiên cần giữ doanh thu. Hóa đơn/báo cáo giữ tổng tiền và thời gian không còn định danh.

## 7. Mã giao tiếp giữa web và thiết bị

Web không gọi MQTT. Admin gửi `open-exit` qua API → Lambda kiểm tra quyền, trạng thái, phí → Lambda publish `gate_command` → ESP ACK → API/dashboard cập nhật. Guest gửi email qua API → SES. Pi/ESP không có quyền gọi SES hoặc xem dữ liệu khách.
