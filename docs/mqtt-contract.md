# Hợp đồng MQTT giữa các module

Tài liệu này là giao kèo tích hợp ban đầu; mọi thay đổi schema cần được cập nhật tại đây và thông báo cho các module liên quan.

## Topic

| Topic | Publisher | Subscriber | Mục đích |
|---|---|---|---|
| `parking/v1/pi-gate-01/events` | Raspberry Pi | Backend/IoT Rule | Sự kiện xe vào/ra từ camera |
| `parking/v1/gate-01/commands` | Backend | ESP32 cổng | Lệnh mở/đóng có thời hạn |
| `parking/v1/gate-01/telemetry` | ESP32 cổng | Backend/dashboard | Trạng thái cần, lỗi, xác nhận lệnh |
| `parking/v1/sensors-01/slots` | ESP32 cảm biến | Backend | Trạng thái các ô |
| `parking/v1/devices/<device-id>/status` | Mỗi thiết bị | Backend/dashboard | Online, phiên bản firmware, lỗi |

## Quy ước chung

- JSON UTF-8; thời gian ISO-8601 UTC; trạng thái rõ ràng, không dùng chuỗi tự do nếu có thể dùng enum.
- Mỗi sự kiện có ID duy nhất và `device_id`; consumer bỏ qua ID đã xử lý.
- Telemetry định kỳ không được xem như lệnh. Backend gửi lệnh có `command_id`, `issued_at`, `expires_at`.
- Thiết bị chỉ subscribe topic được cấp trong IoT policy riêng của nó.
- Payload không chứa AWS secret hoặc dữ liệu liên hệ khách.

## Sự kiện xe

```json
{
  "event_id": "uuid",
  "device_id": "pi-gate-01",
  "type": "vehicle.entry_detected",
  "lane_id": "entry-01",
  "card_color": "green",
  "plate": "51A-123.45",
  "plate_confidence": 0.91,
  "captured_at": "2026-09-30T10:15:00Z"
}
```

`type`: `vehicle.entry_detected` hoặc `vehicle.exit_requested`. `card_color`: `green` hoặc `red`. Nếu OCR không đủ tin cậy, vẫn gửi sự kiện nhưng đặt confidence thấp/null; backend chuyển sang xác nhận thủ công thay vì gán nhầm.

## Lệnh cần chắn

```json
{
  "command_id": "uuid",
  "target": "entry_gate",
  "action": "open",
  "issued_at": "2026-09-30T10:15:01Z",
  "expires_at": "2026-09-30T10:15:06Z",
  "reason": "entry-approved"
}
```

ESP32 xác nhận bằng telemetry có `command_id`, `state` (`OPENING`, `OPEN`, `CLOSING`, `CLOSED`, `ERROR`) và thời gian. Bỏ qua lệnh hết hạn/trùng; lệnh `open` không thay thế cơ chế dừng hành trình tại thiết bị.

## Trạng thái cảm biến ô

```json
{
  "event_id": "uuid",
  "device_id": "sensor-board-01",
  "slot_id": "B07",
  "occupied": false,
  "confidence": 0.98,
  "observed_at": "2026-09-30T10:15:03Z"
}
```

Firmware chỉ phát thay đổi sau debounce/hysteresis; backend lưu thời điểm quan sát để đánh dấu dữ liệu stale nếu mất cập nhật.

## Mã lỗi tối thiểu

`LOW_CONFIDENCE`, `COMMAND_EXPIRED`, `LIMIT_TIMEOUT`, `SENSOR_STALE`, `DEVICE_OFFLINE`, `DUPLICATE_EVENT`, `NO_AVAILABLE_SLOT`.
