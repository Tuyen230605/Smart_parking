# ESP32 `slots-01`: 18 nút giả lập cảm biến ô

Mỗi ô có một nút. Nhấn một lần là ô đổi giữa trống và có xe. Bo mạch gửi thay đổi lên AWS IoT Core ngay, và gửi trạng thái đủ 18 ô khi khởi động, khi kết nối lại và mỗi 30 giây. Trạng thái được lưu trong bộ nhớ của chip nên không mất khi mất điện.

Trạng thái ô chỉ dùng để chỉ chỗ trống trên web. Nó không ảnh hưởng tới phiên đỗ hay tiền.

## Nối dây

Mỗi nút một chân vào GPIO, chân kia vào GND. Không cần điện trở. Bảng chân cho từng ô ở [docs/parking-layout.md](../../docs/parking-layout.md). Ví dụ ô F1-A1 nối GPIO25, F1-A2 nối GPIO26, F1-A3 nối GPIO27. Chân chưa cắm nút thì ô luôn trống.

Không giữ nút của ô F2-C2 và F2-C3 (GPIO15 và GPIO12) đúng lúc cắm điện.

## Nạp

```bash
cd firmware/esp32-slot-sensors
pio run -t upload && pio device monitor
```

Log phải có `✓ đã kết nối AWS IoT` và `snapshot 18 ô`. Wi-Fi và chứng chỉ nằm trong `include/secrets.h` (không commit).

Bo mạch khởi động lại liên tục và log báo `Brownout` là do thiếu điện: cắm bo vào một nguồn USB riêng, không dùng chung cổng với bo khác.
