# ESP32 cổng: hai cần chắn và OLED

Board `gate-01` nhận hai luồng riêng: `gate_command` cho servo `ENTRY`/`EXIT`, `display_command` cho OLED. Gửi ACK/trạng thái theo [MQTT v1](../../docs/mqtt-contract.md). Mỗi command có ID và thời hạn; bỏ lệnh trùng/quá hạn/sai đích.

Hai servo dùng GPIO PWM riêng và nguồn 5 V riêng có mass chung. OLED chỉ hiện ô/đường ngắn, phí và lỗi; QR lớn hiển thị trên kiosk laptop/tablet. Phần cứng MVP không có cảm biến xe qua cổng, nên quản trị xác nhận xe đã ra qua web.
