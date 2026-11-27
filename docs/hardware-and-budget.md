# Phần cứng, nối dây và chi phí

Giá tham khảo tại Việt Nam, kiểm tra tháng 10/2026. Giá thực tế thay đổi theo cửa hàng, VAT và phí vận chuyển. Dòng ghi "ước tính" chỉ để lập kế hoạch.

## Danh sách linh kiện

| Linh kiện | SL | Thành tiền tham khảo | Dùng để |
|---|---:|---:|---|
| Raspberry Pi 5 (4 GB) | 1 | 3.300.000–4.200.000 ₫ | Chạy camera và phát hiện xe |
| Camera cho Pi (OV5647 hoặc Camera Module 3) | 1 | 250.000–1.200.000 ₫ | Nhìn hai làn vào, ra |
| Cáp camera 22 chân sang 15 chân cho Pi 5 | 1 | 50.000–100.000 ₫ ước tính | Pi 5 dùng cổng camera nhỏ |
| Nguồn USB-C 5 V/5 A cho Pi 5 | 1 | khoảng 330.000 ₫ | Nguồn 5 V/3 A (sạc điện thoại) chạy được nhưng dễ sụt điện |
| Thẻ microSD 32 GB | 1 | 200.000–450.000 ₫ ước tính | Hệ điều hành cho Pi |
| ESP32-S3 DevKit | 1 | 150.000–250.000 ₫ ước tính | Điều khiển cần chắn |
| ESP32 DevKit V1 | 1 | khoảng 120.000 ₫ | Đọc 18 nút |
| Servo SG90 | 1 | 35.000–70.000 ₫ ước tính | Cần chắn quay hai hướng |
| Nguồn 5 V riêng cho servo (ví dụ cục sạc điện thoại) | 1 | 50.000–200.000 ₫ ước tính | Servo không lấy điện từ ESP32-S3 được |
| Nút nhấn và dây cắm | 18 | 50.000–130.000 ₫ ước tính | Mỗi ô một nút |
| Breadboard, dây, vật tư điện | 1 bộ | 150.000–300.000 ₫ ước tính | Nối mạch |
| Sa bàn 2 tầng, cần chắn, xe mô hình | 1 bộ | 300.000–700.000 ₫ ước tính | Dựng mô hình |

Tổng khoảng 5–8 triệu đồng, chưa gồm laptop hoặc máy tính bảng dùng làm màn hình QR ở cổng. Nếu đã có sẵn Pi và camera thì chi phí giảm còn khoảng 1 triệu.

## Nối dây

### Raspberry Pi 5

- Camera cắm vào cổng camera bằng cáp 22 sang 15 chân. Mặt có chân kim loại của cáp quay về phía cổng HDMI. Luôn tắt Pi trước khi cắm, rút cáp camera.
- Cáp camera lỏng sẽ làm ảnh bị sọc màu rồi treo, có khi làm Pi tự tắt. Gặp vậy thì tắt Pi và cắm lại cho chặt.
- Pi lên mạng qua dây LAN (xem [setup-guide.md](setup-guide.md) mục 5.1).

### ESP32-S3 `gate-01` (cần chắn)

| Dây servo SG90 | Nối vào |
|---|---|
| Cam hoặc vàng (tín hiệu) | GPIO18 của ESP32-S3 |
| Đỏ (5 V) | 5 V của nguồn riêng |
| Nâu (GND) | GND của nguồn riêng, và nối thêm một dây sang GND của ESP32-S3 |

Không cắm dây đỏ vào chân `5Vin` của ESP32-S3 (chân này thường không có điện khi cắm USB), cũng không cắm vào `3V3`. Dây GND chung là bắt buộc, thiếu thì servo không hiểu tín hiệu.

Có thể lấy 5 V cho servo từ chân số 2 (5 V) và chân số 6 (GND) của Pi, rồi nối GND của Pi với GND của ESP32-S3. Cách này chỉ nên dùng khi Pi có nguồn 5 V/5 A.

Mỗi lần khởi động, servo tự quay 150°, 30° rồi về 90°. Không thấy quay là thiếu nguồn hoặc sai dây.

### ESP32 `slots-01` (18 nút)

Mỗi nút một chân vào GPIO, chân kia vào GND. Không cần điện trở vì chip có sẵn điện trở kéo lên. Bảng chân cho từng ô ở [parking-layout.md](parking-layout.md). Trên một số board, GPIO16 và GPIO17 được in là `RX2` và `TX2`.

### Nguồn

Hai bo ESP32 nên cắm vào hai nguồn USB riêng. Cắm cả hai vào cùng một laptop có thể làm bo ESP32 sụt điện và tự khởi động lại liên tục.

## Chi phí AWS

Chi phí AWS ước tính khoảng 3–5 USD mỗi tháng nếu bãi chạy 12 giờ mỗi ngày (phần lớn do màn hình kiosk và trang quản trị gọi API liên tục). Thực tế khi chạy demo, từ 1/11 đến 27/11/2026 chỉ tốn khoảng 0,09 USD và được tín dụng của tài khoản trừ hết.
