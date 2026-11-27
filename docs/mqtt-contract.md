# Quy ước tin nhắn MQTT (phiên bản 1)

Tài liệu này quy định tin nhắn giữa thiết bị (Pi, hai ESP32) và AWS. Firmware và backend phải làm đúng theo đây. Web không dùng MQTT mà gọi [API](api-contract.md).

## Kênh tin nhắn

Mọi kênh có tiền tố `parking/v1/site-01/`. Mỗi kênh chỉ có một bên được gửi. Quyền này được đặt trong chính sách IoT của từng thiết bị.

| Kênh (bỏ tiền tố) | Bên gửi | Bên nhận | Loại tin |
|---|---|---|---|
| `vision/pi-01/events` | Pi | Lambda | `vehicle_detected` |
| `vision/pi-01/lot` | Lambda | Pi | `lot_state` |
| `slots/slots-01/state` | ESP32 18 nút | Lambda | `slot_changed`, `slots_snapshot` |
| `gates/gate-01/commands` | Lambda | ESP32-S3 | `gate_command` |
| `gates/gate-01/telemetry` | ESP32-S3 | Lambda | `gate_telemetry` |
| `devices/{id}/status` | Thiết bị đó | Lambda | `device_status` |

Ngoài ra còn hai kênh `displays/gate-01/commands` và `displays/gate-01/telemetry` cho màn hình OLED. Firmware vẫn hỗ trợ nếu gắn thêm màn hình, nhưng hệ thống hiện tại không dùng.

## Quy tắc chung

- Tin nhắn ở dạng JSON, có `schema_version: 1`, thời gian theo chuẩn ISO-8601 giờ UTC.
- Mọi tin từ thiết bị có phần đầu chung: `event_id` (mã duy nhất), `device_id`, `boot_id` (mã của lần khởi động), `seq` (số thứ tự tăng dần), `occurred_at`.
- Tin được gửi với QoS 1, nghĩa là có thể đến hai lần. Backend bỏ tin trùng theo `event_id`. ESP32 bỏ lệnh trùng theo `command_id`.
- Lệnh có hạn 5 giây (`expires_at`). Quá hạn thì ESP32 bỏ qua, không chạy lệnh cũ sau khi kết nối lại.
- Không gửi ảnh, email, link QR hay thông tin thanh toán qua MQTT.
- Mạng chặn cổng 8883 thì kết nối qua cổng 443 (cần bật ALPN `x-amzn-mqtt-ca`).

## Có xe ở làn (Pi gửi)

```json
{
  "schema_version": 1,
  "message_type": "vehicle_detected",
  "event_id": "e6221775-e0d6-4c33-913c-fefcb31c90b1",
  "device_id": "pi-01",
  "boot_id": "52d430d8-73d9-4bfa-9f08-88250a399069",
  "seq": 17,
  "occurred_at": "2026-11-25T09:00:00Z",
  "lane_id": "ENTRY",
  "card_color": "GREEN",
  "plate_text": null,
  "plate_confidence": 0
}
```

- `lane_id`: `ENTRY` (làn vào) hoặc `EXIT` (làn ra).
- `card_color`: Pi luôn gửi `GREEN` cho làn vào, `RED` cho làn ra. Trường này giữ lại để sau này có thể dùng thẻ màu. Cặp khác bị bỏ qua.
- `plate_text`: Pi không đọc biển nên gửi `null`. Khi đó backend tự cấp biển số demo. Nếu sau này Pi gửi biển đọc được với `plate_confidence` từ 0,85 trở lên thì backend dùng biển đó.

Pi chỉ gửi một tin cho mỗi lần có vật vào làn. Vật phải rời làn mới tính lượt tiếp theo.

## Danh sách xe (Lambda gửi Pi)

```json
{
  "schema_version": 1,
  "message_type": "lot_state",
  "occurred_at": "2026-11-25T09:45:41.753Z",
  "in_lot": ["11111", "22222"],
  "pending_entry": ["33333"],
  "pending_exit": []
}
```

Lambda gửi mỗi khi danh sách thay đổi và mỗi phút một lần, để Pi vừa khởi động cũng có dữ liệu. IoT Rule bỏ qua loại tin này để nó không quay lại Lambda.

## Trạng thái ô (ESP32 18 nút gửi)

Một ô thay đổi:

```json
{
  "schema_version": 1,
  "message_type": "slot_changed",
  "event_id": "af3cdb82-213e-4df2-9182-e13d08767231",
  "device_id": "slots-01",
  "boot_id": "91270fd2-a4ad-4ccf-a11d-af3657c4e32e",
  "seq": 101,
  "occurred_at": "2026-11-25T09:01:00Z",
  "slot_id": "F1-A1",
  "occupied": true,
  "source": "BUTTON"
}
```

Toàn bộ 18 ô (gửi khi khởi động, khi kết nối lại và mỗi 30 giây):

```json
{
  "schema_version": 1,
  "message_type": "slots_snapshot",
  "event_id": "14eac718-a3fe-41fa-9ae2-391519243470",
  "device_id": "slots-01",
  "boot_id": "91270fd2-a4ad-4ccf-a11d-af3657c4e32e",
  "seq": 102,
  "occurred_at": "2026-11-25T09:01:30Z",
  "slots": [
    {"slot_id": "F1-A1", "occupied": true, "source": "BUTTON"},
    {"slot_id": "F1-A2", "occupied": false, "source": "BUTTON"}
  ]
}
```

Ví dụ trên rút gọn còn 2 ô; tin thật phải có đủ 18 ô. `source` luôn là `BUTTON`. Backend bỏ tin có `seq` cũ hơn trong cùng một `boot_id`. Không nhận được gì trong 90 giây thì mọi ô thành `UNKNOWN`.

## Lệnh mở cần (Lambda gửi ESP32-S3)

```json
{
  "schema_version": 1,
  "message_type": "gate_command",
  "command_id": "6ff2b85d-50bc-4ea4-94bd-5f3430d4cf55",
  "target_device_id": "gate-01",
  "gate": "ENTRY",
  "action": "OPEN",
  "session_id": "01J9F7VRW8MW6W1MJZCQNNMJZP",
  "issued_at": "2026-11-25T09:00:02Z",
  "expires_at": "2026-11-25T09:00:07Z"
}
```

`gate` là `ENTRY` hoặc `EXIT`, `action` là `OPEN` hoặc `CLOSE`. Chỉ có một servo: `ENTRY` quay trái, `EXIT` quay phải, đóng thì về giữa. Đang mở làn này mà có lệnh mở làn kia thì làn cũ báo `CLOSED` trước. Cần tự đóng sau 5 giây.

## Trạng thái cần (ESP32-S3 gửi)

```json
{
  "schema_version": 1,
  "message_type": "gate_telemetry",
  "event_id": "c9ff7d15-b9fb-4318-8b5f-33989d5dd130",
  "device_id": "gate-01",
  "command_id": "6ff2b85d-50bc-4ea4-94bd-5f3430d4cf55",
  "gate": "ENTRY",
  "state": "OPEN",
  "error_code": null,
  "occurred_at": "2026-11-25T09:00:03Z"
}
```

`state` là `OPENING`, `OPEN`, `CLOSING`, `CLOSED` hoặc `ERROR`. Mã lỗi: `COMMAND_EXPIRED`, `DUPLICATE_COMMAND`, `WRONG_TARGET`, `SCHEMA_UNSUPPORTED`. Lệnh không có phản hồi sau 15 giây thì backend tạo cảnh báo.

## Tin báo còn sống

Mỗi thiết bị gửi `device_status` mỗi 30 giây và ngay sau khi kết nối, với `state` là `ONLINE` hoặc `DEGRADED`. Khi thiết bị mất kết nối đột ngột, AWS tự gửi `OFFLINE` thay cho thiết bị (Last Will). Backend coi thiết bị là mất kết nối nếu 90 giây không nhận được gì.
