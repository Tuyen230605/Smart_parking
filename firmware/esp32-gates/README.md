# ESP32-S3 `gate-01`: cần chắn hai hướng

Bo mạch nhận lệnh mở cần từ AWS IoT Core và điều khiển một servo SG90 làm cần chắn chung cho hai làn:

- Cần thẳng (90°): đóng.
- Lệnh mở làn vào (`ENTRY OPEN`): quay trái 90° (180°).
- Lệnh mở làn ra (`EXIT OPEN`): quay phải 90° (0°).
- Sau 5 giây cần tự về giữa.

Đang mở làn này mà có lệnh mở làn kia thì làn cũ được báo đóng, rồi cần quay sang hướng mới. Bo mạch bỏ qua lệnh trùng, lệnh quá hạn 5 giây và lệnh gửi nhầm thiết bị, rồi báo lại từng bước (đang mở, đã mở, đang đóng, đã đóng) theo [quy ước MQTT](../../docs/mqtt-contract.md).

## Nối dây

| Dây servo | Nối vào |
|---|---|
| Cam hoặc vàng (tín hiệu) | GPIO18 |
| Đỏ (5 V) | 5 V của một nguồn riêng |
| Nâu (GND) | GND của nguồn đó, và nối thêm sang GND của ESP32-S3 |

Chân `5Vin` của nhiều bo ESP32-S3 không có điện khi cắm USB, nên servo phải lấy nguồn riêng. Thiếu dây GND chung thì servo không quay.

Mỗi lần khởi động, servo tự quay 150°, 30° rồi về 90°. Không thấy quay là thiếu nguồn hoặc sai dây.

## Nạp

```bash
cd firmware/esp32-gates
pio run -t upload && pio device monitor
```

- Wi-Fi và chứng chỉ nằm trong `include/secrets.h`, do `infra/aws/provision-devices.sh` sinh ra. Tệp này không được commit. ESP32 chỉ dùng Wi-Fi 2,4 GHz.
- Log phải có dòng `✓ đã kết nối AWS IoT`.
- Không nạp được (lỗi `Failed to connect`): giữ nút BOOT, bấm RST, thả BOOT rồi chạy lại lệnh nạp.
- Dùng ESP32 thường thay cho S3: `pio run -e gate-01-esp32 -t upload`.

Góc servo chỉnh ở đầu `src/main.cpp`: `ANGLE_CENTER`, `ANGLE_ENTRY_OPEN`, `ANGLE_EXIT_OPEN`. Phần kết nối Wi-Fi và MQTT dùng chung với bo mạch ô, nằm ở `../common/parking_net.h`.

Firmware vẫn hỗ trợ một màn hình OLED nếu gắn thêm (SDA 8, SCL 9), nhưng hệ thống hiện tại không dùng. Không có màn hình thì bo mạch vẫn chạy bình thường.
