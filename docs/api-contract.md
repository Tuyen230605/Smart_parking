# Hợp đồng REST API v1 và mô hình dữ liệu

Base URL: `https://<api-domain>/v1`. Web app dùng HTTPS/JSON. Thiết bị dùng [MQTT](mqtt-contract.md), không gọi các endpoint này. Tất cả thao tác thay đổi có `Idempotency-Key` do client tạo; backend lưu kết quả theo key để retry an toàn.

## 1. Quyền truy cập

| Vai trò | Cách truy cập | Được thấy/làm |
|---|---|---|
| Public | Không đăng nhập | Sơ đồ ô tổng quan; không thấy biển số/email/phí từng xe |
| Guest phiên | URL QR token ngẫu nhiên, hết hạn sau 15 phút | Ô gợi ý + bản đồ, tự chọn ô khác; gửi một email hướng dẫn; tùy chọn ghi nhớ/bỏ liên kết email với biển số |
| Kiosk | Cognito nhóm `KIOSK` | QR phiên mới nhất và ô/lộ trình để hiện tại cổng; không thấy danh sách biển số |
| Admin | Cognito nhóm `ADMIN` | Danh sách xe trong bãi, Cho vào / Cho ra (mở cần), phí, thiết bị |

Backend kiểm tra quyền tại API, không dựa vào việc ẩn nút trên web. Token QR chứa `session_id`, `claim_nonce` ngẫu nhiên ít nhất 128 bit và thời hạn, được ký HMAC; backend kiểm tra chữ ký, nonce hiện hành và hạn 15 phút. Raw token được tạo lại cho kiosk từ dữ liệu phiên, không lưu trong DB. Không đặt email hoặc biển số trong URL.

## 2. Public và guest

### `GET /public/layout`

Trả 18 ô, `source=BUTTON` (cả 18 ô là nút bấm), trạng thái `AVAILABLE|OCCUPIED|UNKNOWN|OUT_OF_SERVICE` và `updated_at`, không có biển số. Public web và trang QR poll mỗi 5 giây.

### `GET /public/claims/{token}`

Trả mã lượt rút gọn, **ô trống gần cổng nhất lúc hỏi** (`slot_id`, chỉ là gợi ý — phiên không được gán ô; `null` nếu bãi đầy/board ô offline), `route_steps`, `free_count`, `claim_expires_at`, `email_submitted`, `email_auto` (đã tự gửi vì biển số liên kết email) và `linked_email` (email liên kết, đã che). Không trả biển số hay danh sách phiên khác. Web cho khách chọn ô khác và tự vẽ đường đi.

```json
{
  "session_ref": "A7K2",
  "slot_id": "F1-A2",
  "route_steps": ["Qua cổng vào, đi theo lối chính bên trái", "Rẽ phải vào lối đi hàng A", "Ô F1-A2 ở cột 2, phía trên lối đi"],
  "free_count": 12,
  "claim_expires_at": "2026-10-05T09:15:00Z",
  "email_submitted": false,
  "email_auto": false,
  "linked_email": null
}
```

### `POST /public/claims/{token}/email`

```json
{
  "email": "visitor@example.com",
  "consent_for_this_session": true,
  "slot_id": "F2-B3",
  "remember": false
}
```

`slot_id` (tùy chọn): ô khách chọn trên bản đồ, email ghi đường tới ô đó. `remember=true` (khách tự chọn): lưu liên kết biển số ↔ email trong bảng `PlateEmails`; lần sau xe đó được *Cho vào*, backend tự gửi email chỉ dẫn kèm link hủy.

Trả `202 Accepted` và `email_status=QUEUED`. Backend dùng conditional update để một request duy nhất chuyển email sang `QUEUED`, sau đó gọi SES; lưu `ACCEPTED_BY_SES|FAILED` theo kết quả API. Chỉ gọi là `DELIVERED` nếu có feedback giao thư. Từ chối khi token hết hạn, thiếu consent, email sai định dạng hoặc đã gửi trước đó; giới hạn tốc độ theo token/IP. Không tích `remember` thì email chỉ thuộc phiên hiện tại.

### `POST /public/claims/{token}/forget-email`

Bỏ liên kết email với biển số của lượt (nút *Bỏ liên kết email* trên trang QR). Trả `{"linked_email": null}`.

### `POST /public/unsubscribe/{token}`

Link *Hủy liên kết* trong email tự gửi (web `/huy-email/{token}`). Token ký HMAC chứa biển số chuẩn hóa + nonce của liên kết, không hết hạn; liên kết đã đổi/hủy thì coi như xong. Token sai → `404`.

## 3. Kiosk và admin

| Endpoint | Vai trò | Tác dụng |
|---|---|---|
| `GET /kiosk/active-claims` | KIOSK/ADMIN | Phiên vào còn token hiệu lực gồm mã rút gọn, URL QR và ô gợi ý; kiosk hiện QR lớn + bản đồ đường đi |
| `GET /admin/dashboard` | ADMIN | Số ô trống/có xe, thiết bị offline, cảnh báo và `lot` = danh sách xe `in_lot` / `pending_entry` / `pending_exit` |
| `GET /admin/sessions?status=...` | ADMIN | Danh sách phiên, phân trang; biển số/email chỉ khi còn hạn lưu |
| `GET /admin/sessions/{id}` | ADMIN | Chi tiết, thời gian, ô, trạng thái phí/lệnh |
| `POST /admin/sessions/{id}/resolve-plate` | ADMIN | Với phiên `ENTRY_PENDING`: `ENTRY` = **Cho vào** (mở cần vào, xe vào danh sách), `REJECT` = không cho vào |
| `POST /admin/sessions/{id}/renew-claim` | ADMIN | Tạo token QR mới nếu khách đến muộn |
| `POST /admin/sessions/{id}/payment` | ADMIN | Ghi `PAID_CASH` hoặc `WAIVED` và lý do |
| `POST /admin/sessions/{id}/open-exit` | ADMIN | **Cho ra**: chỉ khi `EXIT_REQUESTED` và phí `NO_CHARGE/PAID_CASH/WAIVED`; phát lệnh cần ra và đóng phiên ngay |
| `POST /admin/sessions/{id}/confirm-passage` | ADMIN | Chỉ cho phiên cũ ở `EXIT_OPENED` (luồng trước); luồng mới đóng phiên trong `open-exit` |
| `GET /admin/devices` | ADMIN | Trạng thái Pi, ESP gate, ESP slots và thời điểm cuối |
| `GET /admin/pricing`, `PUT /admin/pricing` | ADMIN | Xem/sửa bảng giá demo |
| `POST /admin/gates/{ENTRY\|EXIT}/command` | ADMIN | Mở/đóng tay một cần (`{"action":"OPEN"}`) để thử cơ cấu; ghi cảnh báo `MANUAL_GATE` |
| `POST /admin/alerts/{id}/ack` | ADMIN | Đánh dấu đã xem một cảnh báo |

`GET /admin/dashboard` trả `alerts` là danh sách `{alert_id, kind, level, message, created_at, session_id?}` chưa xem. `resolve-plate` nhận `{"action":"ENTRY|REJECT","plate_text":"11111","reason":"..."}`. Cần ra **không tự mở** kể cả phí 0 ₫: phí 0 ₫ dùng `open-exit`; có phí thì `payment` ghi `PAID_CASH/WAIVED` xong tự mở cần ra và đóng phiên.

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
| 409 | `SLOT_CONFLICT`, `INVALID_STATE`, `EMAIL_ALREADY_SENT` | Bãi đầy khi cho vào, trạng thái sai/biển đang trong bãi, gửi trùng |
| 410 | `TOKEN_EXPIRED` | QR hết hạn |
| 429 | `RATE_LIMITED` | Gọi quá nhanh |
| 503 | `DEVICE_OFFLINE` | Không thể điều khiển cổng an toàn |

Body lỗi:

```json
{"code":"TOKEN_EXPIRED","message":"Mã QR đã hết hạn","request_id":"uuid"}
```

## 5. Lưu trữ và ràng buộc

### `Slots`

`slot_id` (PK), `floor`, `row`, `column`, `source`, `occupied`, `status`, `sensor_seen_at`, `updated_at`. Chỉ ESP slots cập nhật (trống/có xe) để chỉ chỗ trống; backend không giữ hay gán ô cho phiên.

### `Sessions`

`session_id` (PK), `session_ref`, `state` (`ENTRY_PENDING`, `PARKED`, `EXIT_REQUESTED`, `CLOSED`, `REJECTED`; dữ liệu cũ có thể có `RESERVED`, `EXIT_OPENED`, `MANUAL_REVIEW`), `plate_normalized`, `plate_display`, `plate_collected_at`, `checkin_at`, `charge_end_at`, `exit_opened_at`, `exit_confirmed_at`, `claim_nonce`, `claim_expires_at`, `email`, `email_collected_at`, `email_status`, `email_auto`, `payment_status`, `fee_vnd`, `identity_expires_at`. Không có `slot_id` ở phiên mới.

### `ActivePlates` và thao tác cho vào

`plate_normalized` (PK), `session_id`. Khi quản trị *Cho vào*, một `TransactWriteItems` gồm: chuyển phiên `ENTRY_PENDING → PARKED` có điều kiện và tạo ActivePlates chưa tồn tại. Biển đang có trong bãi → `409 INVALID_STATE`. Khi *Cho ra*, xóa ActivePlates có điều kiện đúng `session_id`. GSI thuần túy không bảo đảm uniqueness.

### `PlateEmails`

`plate_normalized` (PK), `email`, `nonce`, `linked_at`, `linked_session_ref`. Chỉ tạo khi khách tích ghi nhớ; xóa khi bỏ liên kết/hủy qua link. Không có TTL: giữ tới khi khách hủy.

### `ProcessedMessages` và `DeviceStatus`

`event_id` hoặc `command_id` (PK), loại và thời điểm xử lý để dedupe. `device_id` → `last_seen_at`, `state`, `firmware_version`. Idempotency key API được lưu cùng kết quả trong một khoảng đủ cho retry.

### `PricingConfig`

Phiên bản bảng giá, mốc thời gian hiệu lực, miễn phí dưới 15 phút, 10.000 ₫ đến hết 60 phút, 5.000 ₫ cho mỗi giờ tiếp theo bắt đầu. Ví dụ: 61 phút = 15.000 ₫. Phiên lưu phiên bản giá khi check-in để không đổi giá giữa chừng. `charge_end_at` được khóa khi camera thấy xe ở làn ra; `exit_confirmed_at` là lúc quản trị bấm Cho ra. Phí 0 ₫ có `payment_status=NO_CHARGE`.

## 6. Thời hạn dữ liệu

`identity_expires_at` tối đa 10 ngày sau lúc thu thập từng loại định danh. API từ chối trả biển số/email/token đã quá hạn; job purge theo giờ xóa từ mốc 9 ngày 23 giờ và cảnh báo nếu lỗi. DynamoDB TTL chỉ dùng cho item có thể xóa toàn bộ; Lambda xóa thuộc tính định danh khỏi phiên cần giữ doanh thu. Hóa đơn/báo cáo giữ tổng tiền và thời gian không còn định danh.

## 7. Mã giao tiếp giữa web và thiết bị

Web không gọi MQTT. Admin gửi `resolve-plate` (Cho vào) hoặc `open-exit`/`payment` (Cho ra) qua API → Lambda kiểm tra quyền, trạng thái, phí → Lambda publish `gate_command` và `lot_state` → ESP quay servo, Pi cập nhật danh sách → dashboard cập nhật. Guest gửi email qua API → SES. Pi/ESP không có quyền gọi SES hoặc xem dữ liệu khách.
