# API cho web (phiên bản 1)

Địa chỉ gốc: `https://<api>/v1`. Web gọi API qua HTTPS, dữ liệu JSON. Thiết bị không gọi API mà dùng [MQTT](mqtt-contract.md).

## Quyền truy cập

| Đối tượng | Cách truy cập | Được làm gì |
|---|---|---|
| Công khai | Không đăng nhập | Xem sơ đồ 18 ô |
| Khách | Link QR, hết hạn sau 15 phút | Xem ô gợi ý và đường đi, gửi một email, ghi nhớ hoặc bỏ liên kết email |
| Kiosk | Cognito, nhóm `KIOSK` | Lấy mã QR của phiên mới |
| Quản trị | Cognito, nhóm `ADMIN` | Mọi thao tác quản lý |

Quyền được kiểm tra ở Lambda, không dựa vào việc ẩn nút trên web. Các thao tác thay đổi dữ liệu nên gửi kèm header `Idempotency-Key`: gửi lại cùng khóa thì nhận lại đúng kết quả cũ, không chạy lần hai.

## Đường dẫn công khai và của khách

| Đường dẫn | Chức năng |
|---|---|
| `GET /public/layout` | 18 ô với trạng thái `AVAILABLE`, `OCCUPIED`, `UNKNOWN` hoặc `OUT_OF_SERVICE`. Không có biển số |
| `GET /public/claims/{mã}` | Thông tin cho trang QR (xem ví dụ dưới) |
| `POST /public/claims/{mã}/email` | Gửi email hướng dẫn, tùy chọn ghi nhớ email |
| `POST /public/claims/{mã}/forget-email` | Bỏ liên kết email với biển số |
| `POST /public/unsubscribe/{mã}` | Link hủy trong email tự gửi |

Ví dụ `GET /public/claims/{mã}`:

```json
{
  "session_ref": "A7K2",
  "slot_id": "F1-A2",
  "route_steps": ["Qua cổng vào, đi theo lối chính bên trái", "Rẽ phải vào lối đi hàng A", "Ô F1-A2 ở cột 2, phía trên lối đi"],
  "free_count": 12,
  "claim_expires_at": "2026-11-25T09:15:00Z",
  "email_submitted": false,
  "email_auto": false,
  "linked_email": null
}
```

`slot_id` là ô trống gần cổng nhất lúc gọi, chỉ là gợi ý. Bằng `null` nếu bãi đầy hoặc bo mạch ô mất kết nối. `linked_email` là email đã ghi nhớ, được che bớt (ví dụ `kh***@gmail.com`).

Ví dụ gửi email:

```json
{
  "email": "khach@example.com",
  "consent_for_this_session": true,
  "slot_id": "F2-B3",
  "remember": false
}
```

`slot_id` là ô khách chọn trên bản đồ (không bắt buộc). `remember: true` thì lưu email theo biển số để lần sau tự gửi. Mỗi phiên chỉ gửi một email.

## Đường dẫn của kiosk và quản trị

| Đường dẫn | Quyền | Chức năng |
|---|---|---|
| `GET /kiosk/active-claims` | KIOSK, ADMIN | Mã QR của các phiên mới, kèm ô gợi ý |
| `GET /admin/dashboard` | ADMIN | Số ô trống, thiết bị mất kết nối, cảnh báo, danh sách xe (`in_lot`, `pending_entry`, `pending_exit`) |
| `GET /admin/sessions` | ADMIN | Danh sách phiên đỗ, lọc theo trạng thái |
| `GET /admin/sessions/{id}` | ADMIN | Chi tiết một phiên |
| `POST /admin/sessions/{id}/resolve-plate` | ADMIN | Cho vào (`action: ENTRY`) hoặc không cho vào (`action: REJECT`) |
| `POST /admin/sessions/{id}/renew-claim` | ADMIN | Cấp lại mã QR |
| `POST /admin/sessions/{id}/payment` | ADMIN | Ghi đã thu (`PAID_CASH`) hoặc miễn phí (`WAIVED`, cần ghi lý do), rồi mở cần ra |
| `POST /admin/sessions/{id}/open-exit` | ADMIN | Cho ra khi phiên miễn phí |
| `POST /admin/sessions/{id}/confirm-passage` | ADMIN | Đóng phiên ở trạng thái cũ `EXIT_OPENED`; luồng hiện tại không dùng |
| `GET /admin/devices` | ADMIN | Trạng thái 3 thiết bị |
| `GET`, `PUT /admin/pricing` | ADMIN | Xem, sửa bảng giá |
| `POST /admin/gates/{ENTRY\|EXIT}/command` | ADMIN | Mở, đóng cần bằng tay để thử (có ghi cảnh báo) |
| `POST /admin/alerts/{id}/ack` | ADMIN | Đánh dấu đã xem cảnh báo |

Cần ra không bao giờ tự mở. Phiên miễn phí dùng `open-exit`. Phiên có phí dùng `payment`, ghi xong thì tự mở cần và đóng phiên.

## Mã lỗi

| HTTP | `code` | Khi nào |
|---:|---|---|
| 400 | `INVALID_INPUT` | Dữ liệu gửi lên sai |
| 401, 403 | `UNAUTHENTICATED`, `FORBIDDEN` | Chưa đăng nhập hoặc không có quyền |
| 404 | `NOT_FOUND` | Không có phiên hoặc link sai |
| 409 | `SLOT_CONFLICT`, `INVALID_STATE`, `EMAIL_ALREADY_SENT` | Bãi đầy, sai trạng thái (ví dụ biển số đã trong bãi), đã gửi email |
| 410 | `TOKEN_EXPIRED` | Link QR hết hạn |
| 429 | `RATE_LIMITED` | Gọi quá nhanh |
| 503 | `DEVICE_OFFLINE` | Bo mạch cổng mất kết nối |

Nội dung lỗi: `{"code": "TOKEN_EXPIRED", "message": "Mã QR đã hết hạn", "request_id": "..."}`.

## Dữ liệu (DynamoDB)

| Bảng | Khóa | Nội dung |
|---|---|---|
| `slots` | `slot_id` | Trạng thái 18 ô |
| `sessions` | `session_id` | Phiên đỗ: trạng thái, biển số, giờ vào, giờ ra, tiền, thanh toán, email, lịch sử thao tác |
| `active-plates` | `plate_normalized` | Biển số đang trong bãi, bảo đảm một biển chỉ có một phiên |
| `plate-emails` | `plate_normalized` | Email khách tự chọn ghi nhớ |
| `processed` | `message_id` | Mã tin đã xử lý, để bỏ tin trùng |
| `devices` | `device_id` | Lần cuối thấy thiết bị, trạng thái cần, lệnh chờ phản hồi |
| `pricing` | `config_id` | Bảng giá |
| `alerts` | `alert_id` | Cảnh báo cho quản trị |

Khi nhân viên bấm Cho vào, backend dùng một giao dịch DynamoDB để vừa đổi phiên sang `PARKED`, vừa ghi biển số vào `active-plates`. Nếu biển số đã có trong bãi thì cả giao dịch bị hủy và API trả 409.
