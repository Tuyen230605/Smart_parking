# ESP32 ô: một cảm biến và 17 nút

Board `slots-01` đọc cảm biến ToF thật ở `F1-A1` và 17 nút bấm giả lập các ô còn lại theo [bảng ánh xạ](../../docs/parking-layout.md). Hai MCP23017 I²C mở rộng chân. Mỗi nút nhấn hợp lệ đảo `occupied`; lưu trạng thái giả lập trong NVS.

Firmware gửi `slot_changed` ngay khi đổi và `slots_snapshot` đủ 18 ô lúc boot/reconnect, sau đó mỗi 30 giây. Phân biệt `source=SENSOR|BUTTON`, debounce input và dùng [MQTT v1](../../docs/mqtt-contract.md).

## Code và nạp

`src/main.cpp` (ngưỡng ToF `TOF_OCCUPIED_MM`/`TOF_FREE_MM`, debounce 50 ms, snapshot 30 s), `../common/parking_net.h`. `include/secrets.h` do `infra/aws/provision-devices.sh` sinh — không commit.

```bash
cd firmware/esp32-slot-sensors && pio run -t upload && pio device monitor
```

Đấu nối: bus I²C SDA21/SCL22 ở 3,3 V; MCP23017 0x20 (A0–A2 = GND) GPA0..GPB7 = nút B1..B16, MCP23017 0x21 (A0 = VCC) GPA0 = B17; mỗi nút nối chân MCP ↔ GND (pull-up trong). VL53L0X 0x29 nhìn xuống F1-A1; đọc `[tof] mm=…` trên Serial để chỉnh ngưỡng. Trạng thái 17 nút lưu NVS, F1-A1 luôn đọc lại từ cảm biến.
