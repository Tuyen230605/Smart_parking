# ESP32-S3 cổng: một cần chắn 3 vị trí và OLED (tuỳ chọn)

Board `gate-01` nhận hai luồng riêng: `gate_command` cho servo `ENTRY`/`EXIT`, `display_command` cho OLED. Gửi ACK/trạng thái theo [MQTT v1](../../docs/mqtt-contract.md). Mỗi command có ID và thời hạn; bỏ lệnh trùng/quá hạn/sai đích.

Mô hình dùng **một servo SG90** làm cần chắn chung cho hai làn: đóng thì cần **chỉ thẳng** (90°), lệnh `ENTRY OPEN` quay **trái 90°** (180°), lệnh `EXIT OPEN` quay **phải 90°** (0°). Sau `GATE_HOLD_MS` (5 s), cần tự quay về giữa. Backend vẫn coi `ENTRY`/`EXIT` là hai cần logic và nhận telemetry riêng cho từng cần. Nếu một làn đang mở mà có lệnh mở làn kia, làn đang mở báo `CLOSED` rồi cần quay sang hướng mới. OLED chỉ hiện ô/đường ngắn, phí và lỗi; QR lớn hiển thị trên kiosk laptop/tablet. Phần cứng MVP không có cảm biến xe qua cổng, nên quản trị xác nhận xe đã ra qua web.

## Code và nạp

`src/main.cpp` (pin, góc servo, thời gian giữ cần ở đầu file), `../common/parking_net.h` (Wi-Fi, NTP, MQTT/TLS, envelope). `include/secrets.h` do `infra/aws/provision-devices.sh` sinh, chứa Wi-Fi + cert — không commit.

```bash
cd firmware/esp32-gates
pio run -t upload && pio device monitor          # ESP32-S3 (mặc định, env gate-01)
pio run -e gate-01-esp32 -t upload               # nếu dùng ESP32 thường
```

Không nạp được (lỗi `Failed to connect`): giữ nút **BOOT**, bấm **RST**, thả **BOOT**, rồi chạy lại lệnh upload. Nạp xong bấm RST một lần. Env S3 in log qua cổng USB native. Nếu cắm cổng UART/COM mà monitor không ra chữ, đổi `-DARDUINO_USB_CDC_ON_BOOT=0` trong `platformio.ini`.

| Dây SG90 | ESP32-S3 |
|---|---|
| Cam/vàng (tín hiệu) | GPIO18 |
| Đỏ (5 V) | Nguồn 5 V **có điện thật**: chân `5Vin` của nhiều board S3 không có điện khi cấp qua USB (cần nối miếng hàn `IN-OUT`) → lấy từ Pi chân 2 hoặc nguồn riêng |
| Nâu (GND) | GND của nguồn servo, **nối chung** với GND của ESP |

Mỗi lần khởi động servo tự quay thử 150° → 30° → 90° và log `[servo] attach GPIO18 → … attached=1`. Log có mà servo không quay → thiếu nguồn/sai dây, không phải lỗi code.

Muốn đổi chiều quay hoặc chỉnh cho cần thật thẳng thì sửa `ANGLE_ENTRY_OPEN`, `ANGLE_EXIT_OPEN`, `ANGLE_CENTER` ở đầu `src/main.cpp`. OLED SSD1306 0x3C (nếu có): S3 dùng SDA8/SCL9, ESP32 thường dùng SDA21/SCL22. Mất kết nối AWS: OLED hiện `MAT KET NOI`, không tự mở cần. Không có OLED: board vẫn chạy và báo `DEGRADED`.
