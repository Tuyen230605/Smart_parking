# ESP32 ô: một cảm biến và 17 nút

Board `slots-01` đọc cảm biến ToF thật ở `F1-A1` và 17 nút bấm giả lập các ô còn lại theo [bảng ánh xạ](../../docs/parking-layout.md). Hai MCP23017 I²C mở rộng chân. Mỗi nút nhấn hợp lệ đảo `occupied`; lưu trạng thái giả lập trong NVS.

Firmware gửi `slot_changed` ngay khi đổi và `slots_snapshot` đủ 18 ô lúc boot/reconnect, sau đó mỗi 30 giây. Phân biệt `source=SENSOR|BUTTON`, debounce input và dùng [MQTT v1](../../docs/mqtt-contract.md).
