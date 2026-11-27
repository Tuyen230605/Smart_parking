# Sơ đồ bãi đỗ

## Mã ô

Bãi có 2 tầng. Mỗi tầng có 3 hàng (A, B, C) và 3 cột (1, 2, 3), tổng cộng 18 ô. Mã ô có dạng `F<tầng>-<hàng><cột>`, ví dụ `F1-A1`, `F2-C3`. Hàng A gần cổng nhất. Mã ô dùng giống nhau ở mọi nơi: tin nhắn MQTT, API, web và email.

## Cổng

```text
                     [ Raspberry Pi 5 + camera ]
                 vùng làn vào          vùng làn ra
                       |                    |
  Đường đến  -->   [ làn vào ]          [ làn ra ]   <-- Đường ra
                       \                    /
                  [ 1 servo: quay trái = mở vào, quay phải = mở ra ]
                                  |
                           Tầng 1 của bãi
```

Một camera nhìn cả hai làn: nửa trái khung hình là làn vào, nửa phải là làn ra. Màn hình QR (laptop hoặc máy tính bảng) đặt ở cổng vào.

## Tầng 1 và tầng 2

```text
Tầng 1
  Cổng vào
     |      cột 1      cột 2      cột 3
     |    [F1-A1]    [F1-A2]    [F1-A3]
     +------------------------------------   lối đi A
     |    [F1-B1]    [F1-B2]    [F1-B3]
     +------------------------------------   lối đi B
     |    [F1-C1]    [F1-C2]    [F1-C3]
     +------------------------------------>  lối đi C, cuối lối là dốc lên tầng 2

Tầng 2 (giống tầng 1, đi vào từ đầu dốc)
     |    [F2-A1]    [F2-A2]    [F2-A3]
     +------------------------------------   lối đi A
     |    [F2-B1]    [F2-B2]    [F2-B3]
     +------------------------------------   lối đi B
     |    [F2-C1]    [F2-C2]    [F2-C3]
     +------------------------------------   lối đi C
```

Lối chính chạy dọc bên trái. Mỗi hàng có một lối đi ngang ngay dưới hàng ô.

## Gợi ý ô và đường đi

Hệ thống không giữ ô cho xe nào. Ô chỉ để chỉ chỗ trống.

- Ô gợi ý là ô trống đầu tiên theo thứ tự F1-A1 đến F1-C3, rồi F2-A1 đến F2-C3. Ô gợi ý được tính lại mỗi lần khách mở trang.
- Khách chạm vào ô trống khác trên bản đồ để chọn.
- Đường đi: từ cổng vào đi theo lối chính bên trái, tới lối của hàng thì rẽ phải, đi tới cột của ô rồi vào ô.
- Ô ở tầng 2: ở tầng 1 đi hết lối C, lên dốc, rồi ở tầng 2 đi như tầng 1.

Ví dụ chỉ dẫn cho ô `F2-C3`: "Qua cổng vào, đi theo lối chính bên trái đến cuối lối C. Đi hết lối C, lên dốc lên tầng 2. Tầng 2: đi theo lối chính, rẽ phải vào lối đi hàng C. Ô F2-C3 ở cột 3."

Nếu không còn ô trống, trang báo bãi đầy. Nếu bo mạch 18 nút mất kết nối, trang không gợi ý nhưng khách vẫn chọn được ô.

## Nối 18 nút vào ESP32 (`slots-01`)

| Ô | GPIO | Ô | GPIO |
|---|---|---|---|
| F1-A1 | 25 | F2-A1 | 17 (in là `TX2` trên một số board) |
| F1-A2 | 26 | F2-A2 | 18 |
| F1-A3 | 27 | F2-A3 | 19 |
| F1-B1 | 32 | F2-B1 | 21 |
| F1-B2 | 33 | F2-B2 | 22 |
| F1-B3 | 4 | F2-B3 | 23 |
| F1-C1 | 13 | F2-C1 | 5 |
| F1-C2 | 14 | F2-C2 | 15 |
| F1-C3 | 16 (in là `RX2` trên một số board) | F2-C3 | 12 |

Mỗi nút một chân vào GPIO, chân kia vào GND. Nhấn một lần là ô đổi giữa trống và có xe. Chân chưa cắm nút thì coi như ô trống, nên có thể cắm nút dần.

Lưu ý:
- Không giữ nút của ô F2-C2 và F2-C3 (GPIO 15 và 12) đúng lúc cắm điện hoặc nạp code.
- Không dùng GPIO 0 và 2 (nút BOOT, đèn LED), 1 và 3 (cổng nạp code), 6 đến 11 (bộ nhớ flash).
- GPIO 34 đến 39 không có điện trở kéo lên trong chip; nếu dùng thì phải thêm điện trở 10 kΩ lên 3V3.
