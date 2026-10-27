# Phân công chi tiết 4 người

Mỗi người sở hữu **một thiết bị + một phần của web app chung** ([web/](../web/README.md)). Mọi người giao tiếp qua hai hợp đồng: [MQTT v1](mqtt-contract.md) giữa thiết bị và AWS, [REST API v1](api-contract.md) giữa web và backend. Ai cũng làm được ngay bằng mock, không phải chờ người khác.

```text
 Người 1: Pi/camera ──MQTT──┐                        ┌── /s/:token   (người 1)
 Người 2: ESP gate  ──MQTT──┼── AWS IoT → Lambda ──API┼── /kiosk      (người 2)
 Người 3: ESP slots ──MQTT──┘    DynamoDB, SES        ├── /            (người 3)
                                 (người 4)            └── /admin       (người 4)
```

## Quy tắc chung

| Việc | Quy tắc |
|---|---|
| Thư mục | Chỉ sửa thư mục của mình (bảng dưới). File dùng chung (`docs/*-contract.md`, `web/src/api/`, `web/src/App.tsx`, `web/src/styles.css`) sửa qua PR, báo cả nhóm |
| Git | Nhánh `p1/...`, `p2/...`; PR vào `main`, ít nhất một người khác duyệt |
| Đổi hợp đồng | Sửa tài liệu contract + `web/src/api/types.ts` trong cùng PR; người 4 và người bị ảnh hưởng duyệt |
| Bí mật | Không commit cert, private key, `.env`, email/biển số thật |
| ID cố định | `site-01`, `pi-01`, `gate-01`, `slots-01`, ô `F1-A1`…`F2-C3` |
| Mock | Mỗi thiết bị có script mock cùng schema để người khác test khi chưa có phần cứng |

| Người | Thư mục sở hữu | Trang web | Kịch bản SIM chủ trì |
|---|---|---|---|
| 1 | `edge/raspberry-pi-vision/`, `web/src/pages/guest/` | `/s/:token` | 01, 02, 03, 08, 15 |
| 2 | `firmware/esp32-gates/`, `simulation/mock_gate*`, `web/src/pages/kiosk/` | `/kiosk` + điều khiển cổng | 07, 10, 12 |
| 3 | `firmware/esp32-slot-sensors/`, `simulation/mock_slots*`, `web/src/pages/public/`, `web/src/components/FloorMap.tsx` | `/` | 04, 05, 06, 11 |
| 4 | `backend/`, `infra/aws/`, `web/src/pages/admin/`, `web/src/auth.ts` | `/admin` | 09, 13, 14, 16 |

---

## Người 1 — Pi/camera + trang khách

**Đã có:** pipeline nhận thẻ/OCR/publish ([README](../edge/raspberry-pi-vision/README.md)), `mock_pi.py`, khung web app, trang `/s/:token` hoàn chỉnh chạy bằng mock.

Còn lại:
- [ ] Cài lên Pi 5, hiệu chỉnh ROI/HSV/`plate_roi` trên sa bàn, in biển số và thẻ màu.
- [ ] Quay video fixture: vào, ra, sai làn, thiếu sáng. Ghi tỉ lệ đúng màu/biển số (số mẫu + cách tính) cho báo cáo.
- [ ] Nhận cert `pi-01` từ người 4 → chuyển `config.toml` sang AWS IoT, chạy systemd.
- [ ] Nối trang khách với API thật; kiểm tra token hết hạn (410), gửi email trùng (409), không nhập email.

**Bàn giao:** fixture JSON (`python mock_pi.py all --dry-run`) cho người 4; báo cáo độ chính xác.

## Người 2 — ESP32 cổng + kiosk

Firmware `gate-01` (Arduino hoặc ESP-IDF):
- [ ] Hai servo ở **hai GPIO riêng**, nguồn 5 V riêng chung mass; OLED I²C 128×64.
- [ ] Wi-Fi + **đồng bộ NTP** (bắt buộc để so `expires_at`), MQTT TLS tới AWS IoT với cert `gate-01`.
- [ ] Subscribe `gates/gate-01/commands`: bỏ lệnh sai `schema_version`/`target_device_id`, quá `expires_at`, trùng `command_id` (nhớ ~20 ID gần nhất); trả `gate_telemetry` `OPENING → OPEN → CLOSING → CLOSED` hoặc `ERROR` + `error_code`. Tự đóng sau thời gian cấu hình.
- [ ] Subscribe `displays/gate-01/commands`: hiện tối đa 3 dòng × 20 ký tự, ACK `SHOWN`; ưu tiên `ERROR` > `EXIT_FEE` > `ENTRY_ROUTE`.
- [ ] `device_status` mỗi 30 giây, Last Will `OFFLINE`.
- [ ] `simulation/mock_gate.py`: nhận lệnh, trả ACK, có cờ tạo lỗi/timeout để người 4 test.

Web:
- [ ] `/kiosk`: poll `GET /kiosk/active-claims` 2–3 giây, hiện **QR lớn** của phiên mới nhất (thư viện `qrcode`), ô + lộ trình, tự ẩn khi hết hạn, chế độ toàn màn hình.
- [ ] Component trạng thái hai cần + nút mở cổng ra, gọi API `open-exit` của người 4, đặt trong trang admin.

**Bàn giao:** log `gate_telemetry`/`display_telemetry` của cả hai cần; video servo mở đúng cần.

## Người 3 — ESP32 ô + sơ đồ bãi

Firmware `slots-01`:
- [ ] Hai MCP23017 (0x20, 0x21) + VL53L0X (0x29) cùng bus I²C 3,3 V; 17 nút active-low pull-up theo [bảng ánh xạ](parking-layout.md).
- [ ] Nút: debounce, mỗi lần nhấn đảo `occupied`, lưu NVS. ToF: lấy nhiều mẫu + ngưỡng trễ, hiệu chỉnh trên sa bàn thật.
- [ ] `slot_changed` ngay khi đổi; `slots_snapshot` **đủ 18 ô** lúc boot/reconnect và mỗi 30 giây; `boot_id` + `seq`; `device_status`.
- [ ] `simulation/mock_slots.py`: bật/tắt ô từ bàn phím, phát snapshot, giả lập mất kết nối.

Web:
- [ ] `/`: chú thích màu, số ô trống mỗi tầng, nhãn "cảm biến"/"mô phỏng", hiển thị `UNKNOWN` khi board offline, thời điểm cập nhật.
- [ ] Giữ `FloorMap` là component dùng chung: không đổi prop `highlight` vì trang khách đang dùng.

**Bàn giao:** danh sách 18 ID, log snapshot sau boot/reconnect, tỉ lệ phát hiện đúng ToF.

## Người 4 — AWS/backend + quản trị

Hạ tầng (theo [aws-deployment.md](aws-deployment.md)):
- [ ] Region, Budgets 5/10 USD. **Tạo sớm** 3 Thing + cert + policy và gửi riêng cho từng người (không qua git).
- [ ] DynamoDB 6 bảng, IoT Rules → Lambda, API Gateway (CORS cho domain web), Cognito nhóm `ADMIN`/`KIOSK`, SES sender, EventBridge purge, S3 + CloudFront cho web.

Backend:
- [ ] `vehicle_detected` → dedupe → transaction giữ ô + tạo phiên → gửi `gate_command` + `display_command`; ca lỗi chuyển `MANUAL_REVIEW`.
- [ ] Slot state, device status timeout 90 giây, tính phí theo bảng giá, token QR HMAC 15 phút, email SES một lần/phiên.
- [ ] Tất cả endpoint trong [api-contract.md](api-contract.md), trả lỗi đúng `code`.

Web:
- [ ] `src/auth.ts` nối Cognito; `/admin`: dashboard, danh sách/chi tiết phiên, sửa OCR, thu phí, mở cổng ra (dùng component của người 2), xác nhận xe qua, thiết bị, bảng giá.
- [ ] Deploy web; gửi nhóm URL API để điền `VITE_API_BASE_URL`.

**Bàn giao:** URL API + tài khoản demo admin/kiosk, cert từng thiết bị, hướng dẫn deploy.

---

## Thứ tự làm để không ai phải chờ

1. **Song song bằng mock (ngay):** người 1–3 làm firmware với Mosquitto local, làm trang web bằng API giả. Người 4 tạo cert thiết bị trước tiên, rồi dựng backend, test bằng `mock_pi.py`/`mock_gate.py`/`mock_slots.py`.
2. **Nối AWS:** từng thiết bị chuyển sang IoT Core; web đổi `VITE_API_BASE_URL` sang API thật.
3. **Tích hợp:** cả nhóm chạy SIM-01 → SIM-16 ([kế hoạch kiểm thử](simulation-and-test-plan.md)), quay video một lượt vào/ra liên tục.
