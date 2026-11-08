# ESP32 cổng: hai cần chắn và OLED

Board `gate-01` nhận hai luồng riêng: `gate_command` cho servo `ENTRY`/`EXIT`, `display_command` cho OLED. Gửi ACK/trạng thái theo [MQTT v1](../../docs/mqtt-contract.md). Mỗi command có ID và thời hạn; bỏ lệnh trùng/quá hạn/sai đích.

Hai servo dùng GPIO PWM riêng và nguồn 5 V riêng có mass chung. OLED chỉ hiện ô/đường ngắn, phí và lỗi; QR lớn hiển thị trên kiosk laptop/tablet. Phần cứng MVP không có cảm biến xe qua cổng, nên quản trị xác nhận xe đã ra qua web.

## Code và nạp

`src/main.cpp` (pin, góc servo, thời gian giữ cần ở đầu file), `../common/parking_net.h` (Wi-Fi, NTP, MQTT/TLS, envelope). `include/secrets.h` do `infra/aws/provision-devices.sh` sinh, chứa Wi-Fi + cert — không commit.

```bash
cd firmware/esp32-gates && pio run -t upload && pio device monitor
```

Đấu nối mặc định: servo vào GPIO18, servo ra GPIO19 (VCC servo từ nguồn 5 V riêng, GND chung ESP32), OLED SSD1306 0x3C ở SDA21/SCL22. Mất kết nối AWS: OLED hiện `MAT KET NOI`, không tự mở cần. Không có OLED: board vẫn chạy và báo `DEGRADED`.
