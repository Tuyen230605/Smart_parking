# Hợp đồng MQTT v1 giữa thiết bị và AWS

Đây là nguồn chuẩn cho firmware Pi/ESP32 và backend. Thay đổi không tương thích phải tạo `v2` topic, không âm thầm đổi field của `v1`. Web dùng [REST API](api-contract.md), không subscribe trực tiếp AWS IoT Core.

**Bản sửa 1.1 (vẫn là topic `v1`):** ghi rõ phần đầu bắt buộc cho mọi message thiết bị (mục 2), JSON đầy đủ cho ACK OLED, nội dung OLED backend gửi, và cách backend xử lý sự kiện trễ, `seq`, Last Will. Code Pi hiện có đã đúng; firmware ESP chưa viết nên làm theo bản này. Tham chiếu cài đặt: `backend/src/parking/contract.py`.

## 1. Namespace và quyền sở hữu topic

`site_id = site-01`, `pi_id = pi-01`, `gate_id = gate-01`, `slots_id = slots-01`. Mỗi luồng có **một publisher**; không có hai node ghi cùng topic.

| Topic | Publisher duy nhất | Subscriber | Payload |
|---|---|---|---|
| `parking/v1/site-01/vision/pi-01/events` | Pi | IoT Rule → backend | `vehicle_detected` |
| `parking/v1/site-01/slots/slots-01/state` | ESP slots | IoT Rule → backend | `slot_changed`, `slots_snapshot` |
| `parking/v1/site-01/gates/gate-01/commands` | Backend | ESP gate | `gate_command` |
| `parking/v1/site-01/gates/gate-01/telemetry` | ESP gate | IoT Rule → backend | `gate_telemetry` |
| `parking/v1/site-01/displays/gate-01/commands` | Backend | ESP gate/OLED | `display_command` |
| `parking/v1/site-01/displays/gate-01/telemetry` | ESP gate | IoT Rule → backend | `display_telemetry` |
| `parking/v1/site-01/devices/{device_id}/status` | Đúng thiết bị ID đó | IoT Rule → backend | `device_status` |

Không publish biển số lên topic OLED, cảm biến hay public web. Admin xem biển số qua API có xác thực.

## 2. Quy tắc chung

- JSON UTF-8, `schema_version: 1` (số nguyên), ID ô theo [parking-layout.md](parking-layout.md).
- **Phần đầu bắt buộc của mọi message thiết bị gửi lên:** `schema_version`, `message_type`, `event_id` (UUID mới cho mỗi message), `device_id` (phải trùng thiết bị trong topic), `occurred_at` (ISO-8601 **có múi giờ**, ví dụ `2026-10-05T09:00:00Z` hoặc `…000Z`). Thiếu hoặc sai một field, backend bỏ message và ghi log, không retry.
- `boot_id` (UUID mỗi lần khởi động) + `seq` (số nguyên ≥ 0, tăng trong một lần khởi động) **bắt buộc** với `vehicle_detected`, `slot_changed`, `slots_snapshot`, `device_status`; **không bắt buộc** với `gate_telemetry`, `display_telemetry`.
- QoS 1 cho sự kiện/lệnh; xử lý **at least once** bằng `event_id`/`command_id`. `retain=false` cho mọi lệnh và sự kiện. Backend dedupe theo `event_id`; gửi lại cùng message không tạo phiên hay lệnh thứ hai.
- ESP bỏ lệnh trùng `command_id`, lệnh quá `expires_at`, sai `target` hoặc `schema_version`; trả telemetry có `error_code`.
- Command có thời hạn tối đa 5 giây từ lúc phát, không dùng lệnh cũ sau reconnect. ESP tự đưa servo về vị trí đóng sau thời gian demo đã cấu hình và gửi trạng thái.
- Pi gửi một event sau khi màu/biển số ổn định nhiều frame; cùng xe/làn không phát lại trong cửa sổ 5 giây. Backend vẫn phải dedupe.
- MQTT không vận chuyển ảnh nhị phân, email, token QR hoặc thông tin thanh toán.
- Mỗi thiết bị dùng Thing/certificate/policy riêng chỉ cho publish/sub topic trong bảng; backend dùng IAM role.

## 3. Sự kiện từ Pi

```json
{
  "schema_version": 1,
  "message_type": "vehicle_detected",
  "event_id": "e6221775-e0d6-4c33-913c-fefcb31c90b1",
  "device_id": "pi-01",
  "boot_id": "52d430d8-73d9-4bfa-9f08-88250a399069",
  "seq": 17,
  "occurred_at": "2026-10-05T09:00:00Z",
  "lane_id": "ENTRY",
  "card_color": "GREEN",
  "plate_text": "51A-12345",
  "plate_confidence": 0.93
}
```

`lane_id`: `ENTRY` hoặc `EXIT`, lấy từ ROI camera. `card_color`: `GREEN`/`RED`. Hợp lệ khi `ENTRY+GREEN` hoặc `EXIT+RED`; cặp khác chuyển `MANUAL_REVIEW`. `plate_text` có thể là `null` khi OCR thất bại (tối đa 20 ký tự); `plate_confidence` là số 0–1. Ngưỡng confidence khởi điểm 0,85, phải hiệu chỉnh trên bộ ảnh của nhóm; không xem là độ chính xác được bảo đảm.

Backend chuẩn hóa biển số về dạng `51A-12345` / `59X1-23456` (cùng quy tắc với `detector.py` của Pi) và **không mở cần tự động** trong các trường hợp sau; khi đó tạo phiên `MANUAL_REVIEW` và gửi OLED màn `ERROR`:

| `review_reason` | Điều kiện |
|---|---|
| `WRONG_LANE` | Không phải `ENTRY+GREEN` hoặc `EXIT+RED` |
| `STALE_EVENT` | `occurred_at` cũ hơn 60 giây hoặc lệch tương lai quá 30 giây (Pi mất mạng rồi gửi lại; giờ Pi sai). Pi cần đồng bộ NTP |
| `UNREADABLE_PLATE` | `plate_text` null hoặc không khớp mẫu biển số |
| `LOW_CONFIDENCE` | `plate_confidence` < 0,85 |
| `PLATE_ALREADY_ACTIVE` | Xe vào nhưng biển số đang có phiên chưa đóng |
| `SLOTS_UNKNOWN` | Xe vào nhưng slots-01 quá 90 giây không gửi snapshot |
| `NO_ACTIVE_SESSION`, `SESSION_NOT_PARKED` | Xe ra nhưng không có phiên, hoặc phiên chưa ghi nhận đỗ |

Bãi đầy (không còn ô `AVAILABLE`) không tạo phiên; backend gửi OLED màn `LOT_FULL`.

## 4. Trạng thái ô từ ESP slots

### Thay đổi một ô

```json
{
  "schema_version": 1,
  "message_type": "slot_changed",
  "event_id": "af3cdb82-213e-4df2-9182-e13d08767231",
  "device_id": "slots-01",
  "boot_id": "91270fd2-a4ad-4ccf-a11d-af3657c4e32e",
  "seq": 101,
  "occurred_at": "2026-10-05T09:01:00Z",
  "slot_id": "F1-A1",
  "occupied": true,
  "source": "SENSOR"
}
```

`source` là `SENSOR` duy nhất cho F1-A1, `BUTTON` cho 17 ô khác. `occupied` là tín hiệu hiện trường; backend tự chuyển trạng thái nghiệp vụ `RESERVED/OCCUPIED/AVAILABLE`. Cảm biến thật dùng lọc nhiều mẫu; nút dùng debounce và đảo trạng thái trên một lần nhấn.

### Snapshot toàn bộ ô

```json
{
  "schema_version": 1,
  "message_type": "slots_snapshot",
  "event_id": "14eac718-a3fe-41fa-9ae2-391519243470",
  "device_id": "slots-01",
  "boot_id": "91270fd2-a4ad-4ccf-a11d-af3657c4e32e",
  "seq": 102,
  "occurred_at": "2026-10-05T09:01:30Z",
  "slots": [
    {"slot_id": "F1-A1", "occupied": true, "source": "SENSOR"},
    {"slot_id": "F1-A2", "occupied": false, "source": "BUTTON"}
  ]
}
```

Ví dụ rút gọn còn 2 phần tử; message thực tế **phải chứa đủ 18 ID đúng một lần**, `source` đúng bảng ánh xạ, nếu không cả message bị bỏ. Phát snapshot lúc khởi động/reconnect và mỗi 30 giây; thay đổi phát ngay. Backend bỏ snapshot và `slot_changed` có `seq` nhỏ hơn message đã nhận trong cùng `boot_id`; `boot_id` mới (khởi động lại) luôn được nhận. Nếu sau 90 giây không nhận **snapshot**, toàn bộ ô do board này quản lý là `UNKNOWN` và backend không gán ô; `device_status` không thay cho snapshot.

## 5. Lệnh cần chắn và ACK

```json
{
  "schema_version": 1,
  "message_type": "gate_command",
  "command_id": "6ff2b85d-50bc-4ea4-94bd-5f3430d4cf55",
  "target_device_id": "gate-01",
  "gate": "ENTRY",
  "action": "OPEN",
  "session_id": "01J9F7VRW8MW6W1MJZCQNNMJZP",
  "issued_at": "2026-10-05T09:00:02Z",
  "expires_at": "2026-10-05T09:00:07Z"
}
```

`gate` là `ENTRY` hoặc `EXIT`. `action` trong MVP là `OPEN` hoặc `CLOSE`. ESP điều khiển đúng servo của `gate`; không dùng “cần đang rảnh” để chọn servo. Telemetry:

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
  "occurred_at": "2026-10-05T09:00:03Z"
}
```

`state`: `OPENING`, `OPEN`, `CLOSING`, `CLOSED`, `ERROR`. Mã lỗi: `COMMAND_EXPIRED`, `DUPLICATE_COMMAND`, `WRONG_TARGET`, `MOTOR_TIMEOUT`, `SCHEMA_UNSUPPORTED`; `error_code` là `null` khi không lỗi. `command_id` là lệnh đang thực hiện; trạng thái tự phát (tự đóng sau thời gian demo) có thể gửi `command_id: null`. Không đồng nhất `OPEN` với “xe đã qua cổng”.

Backend dùng `OPEN` kèm `command_id` để chuyển phiên: cần vào → `ENTRY_GATE_OPEN`, cần ra → `EXIT_GATE_OPEN`. `ERROR` ghi lỗi vào phiên và trạng thái thiết bị để quản trị thấy. Telemetry nào cũng tính là gate-01 còn online.

## 6. OLED: topic riêng, không lẫn với lệnh motor

```json
{
  "schema_version": 1,
  "message_type": "display_command",
  "command_id": "74c738a2-8c6e-4803-90ca-38161f8cd413",
  "target_device_id": "gate-01",
  "screen": "ENTRY_ROUTE",
  "lines": ["VAO: F1-A1", "Tang 1 - Hang A", "O so 1"],
  "issued_at": "2026-10-05T09:00:02Z",
  "expires_at": "2026-10-05T09:00:17Z"
}
```

`screen`: `ENTRY_ROUTE`, `EXIT_FEE`, `LOT_FULL`, `ERROR`, `IDLE`. `lines` tối đa 3 dòng × 20 ký tự ASCII/không dấu cho OLED mô hình; frontend/email có tiếng Việt đầy đủ. Hai lệnh display và gate có ID riêng, handler riêng. Nếu đến đồng thời, `ERROR` ưu tiên, sau đó `EXIT_FEE`, rồi `ENTRY_ROUTE`; kiosk vẫn hiển thị QR từng phiên. Hạn lệnh display là 15 giây.

Nội dung backend gửi (không bao giờ có biển số):

| `screen` | `lines` |
|---|---|
| `ENTRY_ROUTE` | `["VAO: F1-A1", "Tang 1 - Hang A", "O so 1"]`; tầng 2: `["VAO: F2-C3", "Len tang 2 - Hang C", "O so 3"]` |
| `EXIT_FEE` | `["RA - PHI GUI XE", "Phi: 15000 VND", "Thanh toan tai cong"]`; 0 ₫: `["RA - MIEN PHI", "Phi: 0 VND", "Cho nhan vien"]`; khi quản trị mở cần: `["RA - MOI XE QUA", "Cam on quy khach"]` |
| `LOT_FULL` | `["BAI DA DAY", "Vui long quay lai", "sau it phut"]` |
| `ERROR` | `["CHO NHAN VIEN", "Cong vao", "Vui long doi"]` (hoặc `Cong ra`) |

ACK trên topic display telemetry, cùng phần đầu bắt buộc như mọi message thiết bị:

```json
{
  "schema_version": 1,
  "message_type": "display_telemetry",
  "event_id": "0d6c1a3e-5b7f-4f0e-9a51-2c8e4b7d9f10",
  "device_id": "gate-01",
  "command_id": "74c738a2-8c6e-4803-90ca-38161f8cd413",
  "state": "SHOWN",
  "occurred_at": "2026-10-05T09:00:02Z"
}
```

`state`: `SHOWN` hoặc `ERROR`.

## 7. Device status

Mỗi thiết bị publish `device_status` mỗi 30 giây và sau reconnect, gồm `schema_version`, `message_type: "device_status"`, `event_id`, `device_id`, `boot_id`, `seq`, `occurred_at`, `state=ONLINE|DEGRADED`, `firmware_version` (chuỗi ≤ 32 ký tự). Backend đánh dấu OFFLINE nếu 90 giây không nhận tin còn sống: `device_status`, với gate-01 thêm `gate_telemetry`/`display_telemetry`, với slots-01 thêm `slots_snapshot`. `vehicle_detected` và `slot_changed` không tính, nên Pi vẫn phải gửi `device_status` đều đặn. Thiết bị có thể cấu hình MQTT Last Will với `state=OFFLINE`; vì Last Will được tạo lúc kết nối nên `occurred_at`/`seq` của nó cũ, backend không xét thứ tự cho `device_status` và không coi OFFLINE là tin còn sống. Timeout backend vẫn là nguồn quyết định.

Client ID MQTT phải đúng tên Thing (`pi-01`, `gate-01`, `slots-01`): policy AWS IoT chỉ cho phép client ID đó. Mock và thiết bị thật cùng tên không chạy song song trên AWS được, vì kết nối sau đẩy kết nối trước ra.

## 8. Tương ứng với API và database

Pi/ESP không lưu email, QR hoặc DynamoDB key; ESP gate chỉ hiển thị chữ/phí do backend gửi, không tự tính tiền. Backend chuyển `vehicle_detected` thành phiên, gửi gate/display command, đưa dữ liệu phiên cho web qua REST. `slot_changed` và `slots_snapshot` chỉ cập nhật cảm biến; không được tự ghi đè `RESERVED` của backend. Ô được gán báo `occupied=true` thì phiên sang `PARKED`.

Thử firmware không cần AWS: chạy backend local với Mosquitto (`backend/README.md`, mục chạy local) rồi trỏ thiết bị/mock tới broker đó; lệnh `gate_command`/`display_command` được phát lại lên broker.
