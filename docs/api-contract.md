# Hợp đồng REST API v1.1 và mô hình dữ liệu

Base URL: `https://<api-id>.execute-api.ap-southeast-2.amazonaws.com/v1` (output `ApiUrl` của stack). Web app dùng HTTPS/JSON. Thiết bị dùng [MQTT](mqtt-contract.md), không gọi các endpoint này. Kiểu TypeScript tương ứng nằm ở `web/src/api/types.ts`.

**v1.1 so với v1:** viết đủ request/response cho 15 endpoint, thêm `INTERNAL_ERROR`, quy tắc `Idempotency-Key`, trạng thái phiên `RESOLVED`/`DISMISSED`, `payment_status=PENDING`, lý do chờ xử lý và phân trang. Endpoint/field cũ giữ nguyên ý nghĩa; field mới là bổ sung nên client v1 vẫn chạy. Tham chiếu cài đặt: `backend/src/parking/`.

## 1. Quyền truy cập

| Vai trò | Cách truy cập | Được thấy/làm |
|---|---|---|
| Public | Không đăng nhập | Sơ đồ ô tổng quan; không thấy biển số/email/phí từng xe |
| Guest phiên | URL QR token ngẫu nhiên, hết hạn sau 15 phút | Ô và lộ trình của phiên; có thể gửi một email hướng dẫn |
| Kiosk | Cognito nhóm `KIOSK` | QR phiên mới nhất và ô/lộ trình để hiện tại cổng; không thấy danh sách biển số |
| Admin | Cognito nhóm `ADMIN` | Phiên, phí, thiết bị, xử lý lỗi, xác nhận thu tiền/xe ra |

Kiosk/admin gửi `Authorization: Bearer <access token Cognito>`. API Gateway kiểm chữ ký JWT; Lambda kiểm nhóm (`cognito:groups`) cho từng route, không dựa vào việc ẩn nút trên web. Tài khoản do quản trị tạo, lần đầu đăng nhập phải đổi mật khẩu tạm.

Token QR có dạng `session_id.nonce.hạn.chữ_ký`: `nonce` ngẫu nhiên 128 bit, `hạn` là epoch giây, chữ ký HMAC-SHA256 (cắt 128 bit). Backend kiểm chữ ký, nonce hiện hành của phiên và hạn 15 phút. Token không lưu trong DB; kiosk lấy lại URL vì backend ký lại từ dữ liệu phiên. Không đặt email hoặc biển số trong URL.

## 2. Quy tắc chung

- **Idempotency-Key:** bắt buộc với mọi request thay đổi dữ liệu (`POST`, `PUT`), 8–64 ký tự `A-Z a-z 0-9 _ -`. Gửi lại cùng key cho cùng thao tác trả kết quả hiện tại mà không làm lại (không gửi email/lệnh cổng lần hai), kể cả khi đã có key mới hơn; backend nhớ key ít nhất 24 giờ. Client giữ key khi thử lại sau lỗi mạng/5xx; tạo key mới sau khi thành công hoặc sau lỗi 4xx.
- **Thời gian:** ISO-8601 UTC có mili giây, ví dụ `2026-10-29T02:00:00.000Z`. Field chưa có giá trị trả `null`.
- **Dữ liệu định danh:** biển số/email chỉ trả cho admin và chỉ khi chưa quá hạn 10 ngày; quá hạn trả `null` dù job xóa chưa chạy.
- **Audit:** mỗi thao tác admin thêm một mục `{action, at, actor_id, actor, reason?, detail?}` vào phiên (hoặc bảng giá); không chứa biển số/email.

## 3. Public và guest

### `GET /public/layout`

Đủ 18 ô theo thứ tự `F1-A1` … `F2-C3`, không có biển số. Poll 5–10 giây.

```json
{"slots": [
  {"slot_id": "F1-A1", "source": "SENSOR", "status": "RESERVED", "updated_at": "2026-10-29T02:00:00.000Z"},
  {"slot_id": "F1-A2", "source": "BUTTON", "status": "AVAILABLE", "updated_at": "2026-10-29T02:00:00.000Z"}
]}
```

`status` suy ra lúc đọc, theo thứ tự ưu tiên: `OUT_OF_SERVICE` → `UNKNOWN` (slots-01 quá 90 giây không gửi snapshot) → `OCCUPIED` (cảm biến/nút báo có xe) → `RESERVED` (backend đang giữ cho một phiên) → `AVAILABLE`. `updated_at` là lần xác nhận gần nhất (ô đổi trạng thái hoặc snapshot mới nhất); `null` nếu ô chưa từng có dữ liệu.

### `GET /public/claims/{token}`

```json
{
  "session_ref": "A7K2",
  "slot_id": "F1-A1",
  "route_steps": ["Tầng 1", "Đi đến hàng A", "Ô số 1"],
  "claim_expires_at": "2026-10-29T02:15:00.000Z",
  "email_submitted": false
}
```

Không trả biển số, email đã nhập hay phiên khác. Token sai định dạng/chữ ký → `404 NOT_FOUND` (không tiết lộ phiên nào tồn tại). Token hết hạn, đã bị cấp lại hoặc phiên không còn ở bãi → `410 TOKEN_EXPIRED`.

### `POST /public/claims/{token}/email`

Header `Idempotency-Key`. Body:

```json
{"email": "visitor@example.com", "consent_for_this_session": true}
```

Trả `202 {"email_status": "QUEUED"}`. Một email mỗi phiên: conditional update chuyển phiên sang `QUEUED` rồi gọi SES, sau đó ghi `ACCEPTED_BY_SES` hoặc `FAILED` (chỉ admin thấy). SES lỗi không làm hỏng phiên. Chỉ gọi là `DELIVERED` nếu sau này bật feedback giao thư. Email này chỉ thuộc phiên hiện tại và bị xóa khi phiên đóng.

| Lỗi | Khi nào |
|---|---|
| `400 INVALID_INPUT` | Thiếu key, email sai hoặc quá 254 ký tự, `consent_for_this_session` khác `true` |
| `404 NOT_FOUND`, `410 TOKEN_EXPIRED` | Như `GET` ở trên |
| `409 EMAIL_ALREADY_SENT` | Phiên đã gửi với key khác |
| `429 RATE_LIMITED` | API Gateway giới hạn route này 1 request/giây, burst 5 |

## 4. Kiosk

### `GET /kiosk/active-claims` (KIOSK, ADMIN)

Phiên còn QR hiệu lực (trạng thái `RESERVED`, `ENTRY_GATE_OPEN`, `PARKED`), **mới nhất trước**. URL ổn định giữa các lần poll vì token được ký lại từ cùng dữ liệu.

```json
[{
  "session_ref": "A7K2",
  "slot_id": "F1-A1",
  "route_steps": ["Tầng 1", "Đi đến hàng A", "Ô số 1"],
  "claim_url": "https://<web>/s/<token>",
  "claim_expires_at": "2026-10-29T02:15:00.000Z",
  "created_at": "2026-10-29T02:00:00.000Z"
}]
```

## 5. Quản trị (ADMIN)

### Trạng thái phiên

| `state` | Nghĩa |
|---|---|
| `RESERVED` | Đã giữ ô, đã phát lệnh mở cần vào |
| `ENTRY_GATE_OPEN` | gate-01 báo cần vào đã mở |
| `PARKED` | Ô được gán báo có xe |
| `PAYMENT_PENDING` | Xe yêu cầu ra, phí > 0 đã chốt, chờ thu tiền |
| `EXIT_REQUESTED` | Sẵn sàng mở cần ra (phí 0 ₫, hoặc đã thu/miễn) |
| `EXIT_GATE_OPEN` | gate-01 báo cần ra đã mở |
| `CLOSED` | Quản trị xác nhận xe đã qua cổng |
| `EXPIRED` | Giữ ô quá 5 phút mà ô không báo có xe |
| `MANUAL_REVIEW` | Sự kiện xe không chắc chắn, chờ quản trị (xem `review_reason`) |
| `RESOLVED` / `DISMISSED` | Phiên chờ xử lý đã được cho vào/ra, hoặc bỏ qua |

`payment_status`: `PENDING`, `NO_CHARGE`, `PAID_CASH`, `WAIVED`. `review_reason`: `WRONG_LANE`, `STALE_EVENT`, `UNREADABLE_PLATE`, `LOW_CONFIDENCE`, `PLATE_ALREADY_ACTIVE`, `SLOTS_UNKNOWN`, `NO_ACTIVE_SESSION`, `SESSION_NOT_PARKED` (ý nghĩa ở [use-cases.md](use-cases.md) UC-07). Sơ đồ chuyển trạng thái ở [use-cases.md](use-cases.md).

### `GET /admin/dashboard`

```json
{
  "available": 15, "reserved": 1, "occupied": 2, "unknown": 0,
  "offline_devices": ["pi-01"],
  "alerts": ["Thiết bị pi-01 mất kết nối", "1 lượt chờ quản trị xử lý"]
}
```

`alerts` là chuỗi tiếng Việt để hiển thị, không chứa biển số/email: thiết bị offline, snapshot ô cũ, ô có xe mà không có phiên, ô giữ quá 5 phút, cần báo lỗi, lượt chờ xử lý, lượt giữ ô hết hạn trong 1 giờ, phiên còn mở sắp bị xóa biển số trong 24 giờ.

### `GET /admin/sessions?status=&limit=&cursor=`

`status` (không bắt buộc) là một giá trị `state`; `limit` 1–100, mặc định 20; `cursor` lấy từ `next_cursor` của trang trước. Mới nhất trước.

```json
{"sessions": [{
  "session_id": "01M63ZZR56DFFS9M84NA0K2C5Z", "session_ref": "JNZW", "state": "PARKED",
  "lane_id": "ENTRY", "slot_id": "F1-A2", "review_reason": null,
  "created_at": "…", "checkin_at": "…", "parked_at": "…", "charge_end_at": null, "exit_confirmed_at": null,
  "fee_vnd": null, "payment_status": null, "email_status": null, "plate_confidence": 0.93,
  "plate_normalized": "30F-67890"
}], "next_cursor": "eyJ…"}
```

### `GET /admin/sessions/{id}`

Như một phần tử danh sách, thêm: `card_color`, `plate_text` (chuỗi OCR gốc), `email`, `related_session_id`, `resolution`, `resolved_session_id`, `resolved_from_session_id`, `claim_expires_at`, `entry_command_id`, `exit_command_id`, `entry_gate_opened_at`, `exit_gate_opened_at`, `gate_error`, `paid_amount_vnd`, `payment_note`, `paid_at`, `pricing` (bảng giá chép lúc vào), `closed_at`, `updated_at`, `audit`.

### Thao tác trên phiên

Tất cả cần `Idempotency-Key`; `reason` tối đa 200 ký tự. Gọi sai trạng thái → `409 INVALID_STATE`.

| Endpoint | Body | Điều kiện và kết quả |
|---|---|---|
| `POST /admin/sessions/{id}/resolve-plate` | `{"action": "ENTRY"\|"EXIT"\|"DISMISS", "plate_text": "51A-12345", "reason": "…"}` | Chỉ phiên `MANUAL_REVIEW`; `reason` bắt buộc, `plate_text` bắt buộc trừ `DISMISS`. `ENTRY`: tạo phiên `RESERVED` mới như xe vào bình thường. `EXIT`: chốt phí cho phiên đang ở bãi của biển số đó, **tính đến lúc xe tới cổng ra** (lúc tạo phiên chờ xử lý). Trả `200 {"review": …, "session": … \| null, "commands_sent": true}` |
| `POST …/renew-claim` | `{"reason"?: "…"}` | Phiên `RESERVED`/`ENTRY_GATE_OPEN`/`PARKED`. Nonce và hạn mới, QR cũ trả 410 ngay. Trả `200` như một phần tử của `/kiosk/active-claims` |
| `POST …/payment` | `{"payment_status": "PAID_CASH", "amount_vnd": 15000, "note"?: "…"}` hoặc `{"payment_status": "WAIVED", "note": "…"}` | Phiên `PAYMENT_PENDING`. `PAID_CASH`: `amount_vnd` phải bằng `fee_vnd` đã chốt. `WAIVED`: `note` bắt buộc. Phiên sang `EXIT_REQUESTED`; trả `200` chi tiết phiên |
| `POST …/open-exit` | `{"reason"?: "…"}` | Phiên `EXIT_REQUESTED`/`EXIT_GATE_OPEN` và `payment_status` là `NO_CHARGE`/`PAID_CASH`/`WAIVED`; gate-01 online. Phát `gate_command` EXIT OPEN, trả `202 {"command_id": "…", "session": …}`. Gọi lại với key mới để mở lại cần |
| `POST …/confirm-passage` | `{"reason"?: "…"}` | Đã có `exit_command_id`. Phiên `CLOSED`, bỏ khóa biển số và giữ ô, xóa email; ô về `AVAILABLE` khi cảm biến báo trống. Trả `200` chi tiết phiên |

Lỗi riêng của `resolve-plate` khi cho vào: bãi đầy → `409 SLOT_CONFLICT`; biển số đang có phiên mở → `409 INVALID_STATE`; slots-01 không có dữ liệu mới → `503 DEVICE_OFFLINE`. Khi lệnh cổng không phát được, `commands_sent=false` và quản trị thao tác tay. `open-exit` trả `503 DEVICE_OFFLINE` nếu gate-01 quá 90 giây không gửi tin hoặc không gửi được lệnh; thử lại cùng key là an toàn.

**G3 chưa chốt:** phiên 0 ₫ hiện vẫn chờ quản trị bấm `open-exit`, chưa tự mở cần ra.

### `GET /admin/devices`

```json
{"devices": [
  {"device_id": "pi-01", "online": true, "state": "ONLINE", "last_seen_at": "…", "firmware_version": "0.1.0"},
  {"device_id": "gate-01", "online": true, "state": "ONLINE", "last_seen_at": "…", "firmware_version": "0.1.0",
   "gates": {"ENTRY": {"state": "CLOSED", "error_code": null, "updated_at": "…"},
             "EXIT": {"state": "OPEN", "error_code": null, "updated_at": "…"}},
   "display": {"state": "SHOWN", "updated_at": "…"}},
  {"device_id": "slots-01", "online": true, "state": "ONLINE", "last_seen_at": "…", "firmware_version": "0.1.0",
   "last_snapshot_at": "…", "snapshot_fresh": true}
]}
```

`online=false` khi quá 90 giây không có tin hoặc thiết bị báo `OFFLINE` (Last Will).

### `GET /admin/pricing`, `PUT /admin/pricing`

```json
{"version": 2, "free_minutes": 15, "first_block_minutes": 60, "first_block_vnd": 10000, "extra_hour_vnd": 5000,
 "updated_at": "…", "updated_by": "<cognito sub>"}
```

`PUT` (cần `Idempotency-Key`) gửi 4 số nguyên và `reason` tùy chọn: `free_minutes` 0–1440, `first_block_minutes` 1–1440 và không nhỏ hơn `free_minutes`, hai mức giá 0–10.000.000 ₫. Mỗi lần lưu tăng `version`; bị sửa đồng thời → `409 INVALID_STATE`. Phiên chép bảng giá lúc vào nên đổi giá không ảnh hưởng xe đang trong bãi.

Công thức: dưới `free_minutes` → 0 ₫; đến hết `first_block_minutes` → `first_block_vnd`; mỗi giờ tiếp theo **bắt đầu** cộng `extra_hour_vnd`. Với giá mặc định: 14 phút 59 giây = 0 ₫, 15 phút = 10.000 ₫, 61 phút = 15.000 ₫, 121 phút = 20.000 ₫.

## 6. Mã lỗi thống nhất

| HTTP | `code` | Tình huống |
|---:|---|---|
| 400 | `INVALID_INPUT` | Body/query/email/giá/biển số không hợp lệ, thiếu `Idempotency-Key` |
| 401 | `UNAUTHENTICATED` | Thiếu hoặc hết hạn token |
| 403 | `FORBIDDEN` | Sai nhóm Cognito |
| 404 | `NOT_FOUND` | Không có phiên/token/endpoint |
| 409 | `SLOT_CONFLICT` | Không còn ô trống khi quản trị cho xe vào |
| 409 | `INVALID_STATE` | Trạng thái phiên không cho phép, số tiền khác phí đã chốt, dữ liệu vừa bị sửa |
| 409 | `EMAIL_ALREADY_SENT` | Phiên đã gửi email |
| 410 | `TOKEN_EXPIRED` | QR hết hạn hoặc đã bị cấp lại |
| 429 | `RATE_LIMITED` | Gọi quá nhanh |
| 500 | `INTERNAL_ERROR` | Lỗi máy chủ; thử lại cùng `Idempotency-Key` |
| 503 | `DEVICE_OFFLINE` | gate-01/slots-01 không sẵn sàng, không thể điều khiển cổng an toàn |

Body lỗi:

```json
{"code": "TOKEN_EXPIRED", "message": "Mã QR đã hết hạn", "request_id": "uuid"}
```

API Gateway có thể tự trả 401/403/429/5xx với body `{"message": "…"}` không có `code`. Client suy `code` theo HTTP status như bảng trên (`web/src/api/http.ts`), không coi là `INVALID_INPUT`.

## 7. Lưu trữ và ràng buộc

### `Slots`

`slot_id` (PK), `source`, `occupied` (tín hiệu hiện trường), `reserved_session_id`, `reserved_at`, `out_of_service`, `src_boot_id`, `src_seq`, `updated_at`. Trạng thái công khai suy ra lúc đọc (mục 3), không lưu. Gán ô bằng conditional write: chỉ khi `occupied=false`, chưa có `reserved_session_id`, không `out_of_service` và slots-01 có snapshot trong 90 giây. Message ô cũ hơn (`seq` nhỏ hơn trong cùng `boot_id`) bị bỏ.

### `Sessions`

`session_id` (PK, ULID), `session_ref`, `site_id`, `state`, `lane_id`, `card_color`, `slot_id`, `plate_normalized`, `plate_text`, `plate_confidence`, `plate_collected_at`, `identity_expires_at`, `purge_due_at`, `checkin_at`, `parked_at`, `charge_end_at`, `exit_confirmed_at`, `closed_at`, `claim_nonce`, `claim_expires_at`, `email`, `email_collected_at`, `email_expires_at`, `email_status`, `pricing`, `fee_vnd`, `payment_status`, `paid_amount_vnd`, `payment_note`, `review_reason`, `entry_command_id`, `exit_command_id`, `audit`, `created_at`, `updated_at`.

Index: `by_state` (`state`, `created_at`), `by_site` (`site_id`, `created_at`), `active_claims` (`claim_pk`, `claim_expires_at`, chỉ phiên còn QR, không chiếu biển số/email), `purge_due` (`pii_pk`, `purge_due_at`, chỉ phiên còn dữ liệu định danh).

Idempotency, theo hai loại thao tác. Thao tác chỉ thành công được một lần (email, `resolve-plate`, `payment`, `confirm-passage`) lưu key ngay trên phiên (`email_idempotency_key`, `payment_idempotency_key`, …) trong cùng lần ghi có điều kiện. Thao tác lặp lại được (`open-exit`, `renew-claim`, `PUT /admin/pricing`) ghi dấu `idem#<thao tác>#<phạm vi>#<key>` vào `ProcessedMessages` trong cùng transaction, nên key cũ gửi lại sau một key mới hơn vẫn không chạy lần hai. Không lưu bản sao response, nên không giữ dữ liệu định danh ngoài phiên.

### `ActivePlates` và thao tác tạo phiên

`plate_normalized` (PK), `session_id`. Một `TransactWriteItems` gồm: dấu `event_id` đã xử lý, tạo ActivePlates chưa tồn tại, kiểm snapshot slots-01 còn mới, giữ ô có điều kiện, tạo Session, ghi `command_id` → phiên. Hai xe tranh ô hay cùng biển số thì chỉ một transaction thành công; backend thử ô kế tiếp khi **chỉ** có slot conflict. Đóng, hết hạn hoặc xóa định danh phiên thì xóa ActivePlates có điều kiện đúng `session_id`. GSI thuần túy không bảo đảm uniqueness.

### `ProcessedMessages`, `DeviceStatus`, `PricingConfig`

- `ProcessedMessages`: `message_id` (PK) là `event_id` đã xử lý hoặc `cmd#<command_id>` ánh xạ lệnh cổng về phiên để ACK `OPEN` chuyển đúng phiên (TTL 7 ngày), hoặc dấu `idem#…` của Idempotency-Key (TTL 24 giờ, `open-exit` lưu kèm `command_id`).
- `DeviceStatus`: `device_id` (PK), `state`, `last_seen_at`, `firmware_version`; slots-01 thêm `last_snapshot_at`; gate-01 thêm trạng thái/lỗi từng cần và OLED.
- `PricingConfig`: item `current` chứa `rules` (`version` + 4 số), `updated_at`, `updated_by`, `audit`.

## 8. Thời hạn dữ liệu

`identity_expires_at` = thời điểm thu thập + 10 ngày; API ngừng trả biển số/email/token tại mốc này. Job `purge_identity` chạy mỗi giờ, xóa từ `purge_due_at` (9 ngày 23 giờ): bỏ `plate_normalized`, `plate_text`, `email`, nonce QR, khóa `ActivePlates`, giữ phí, thời gian và audit để báo cáo. Phiên còn mở cũng bị xóa đúng hạn; dashboard cảnh báo trước 24 giờ để quản trị đóng phiên. Job lỗi kích hoạt alarm. CloudWatch log không ghi biển số, email hay token.

## 9. Mã giao tiếp giữa web và thiết bị

Web không gọi MQTT. Admin gửi `open-exit` qua API → Lambda kiểm quyền, trạng thái, phí, gate-01 online → publish `gate_command` → ESP ACK → phiên `EXIT_GATE_OPEN`, web thấy qua poll. Guest gửi email qua API → SES. Pi/ESP không có quyền gọi SES hoặc xem dữ liệu khách.
