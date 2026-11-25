# Sơ đồ mô hình bãi xe: 2 tầng, mỗi tầng 3 × 3 ô

Đây là sơ đồ logic để bố trí mô hình và tính đường đi; kích thước thật của mô hình cần đo sau khi làm mặt bãi. ID ô được dùng thống nhất trong MQTT, API, web, OLED và email.

## Quy ước

- `F1` = tầng 1, `F2` = tầng 2; `A/B/C` = hàng gần đến xa; `1/2/3` = cột từ trái sang phải.
- Có **18 ô**, mỗi ô một nút bấm giả lập nối thẳng vào GPIO của ESP32 `slots-01` (sơ đồ chân ở đầu `firmware/esp32-slot-sensors/src/main.cpp`).
- Hai làn vào/ra riêng và hai cần chắn riêng, cùng nằm trong góc nhìn camera Pi.
- Mũi tên thể hiện chiều xe đi trong mô hình. Đường lên tầng 2 là ram dốc tượng trưng; phần cứng có thể là hai mặt bãi xếp tầng.

## Cổng và làn

```text
                          [1 CAMERA + PI 5]
                    ROI vào             ROI ra
                       ↓                   ↓
       Đường đến  ──> [XE / TAY]       [XE / TAY] <── Đường ra
                        │                   │
                  [1 SERVO: trái = VÀO, phải = RA]
                        │                   │
                 [OLED chỉ ô]         [OLED hiện phí]
                        │                   │
                    ┌───┴───────────────────┴───┐
                    │ TẦNG 1: lối đi một chiều │
                    └──────────┬────────────────┘
                               │ lên/xuống F2

       Kiosk/laptop tại cổng vào hiển thị QR phiên lớn để khách quét.
       Một OLED gắn ESP gate luân phiên hiện chỉ dẫn cổng vào/phí cổng ra.
```

**Lưu ý:** một OLED dùng chung cần ưu tiên thông báo sự kiện mới nhất và ghi rõ `VÀO`/`RA`; nếu hai làn hoạt động đồng thời, kiosk/web vẫn hiển thị thông tin theo phiên. Camera chỉ phát sự kiện khi có vật nằm ổn định trong đúng ROI; quản trị bấm Cho vào/Cho ra thì cần mới mở.

## Tầng 1

```text
       Cổng vào → lối chính (A gần cổng nhất, C gần ram dốc nhất)
                     cột 1         cột 2         cột 3
  Hàng A          [F1-A1 *]     [F1-A2]       [F1-A3]
                     │              │             │
  Lối đi A ─────────────────────────────────────────────→
  Hàng B          [F1-B1]       [F1-B2]       [F1-B3]
                     │              │             │
  Lối đi B ─────────────────────────────────────────────→
  Hàng C          [F1-C1]       [F1-C2]       [F1-C3]
                     │              │             │
  Lối đi C ─────────────────────────────────────────────→ ram lên F2

  Mỗi ô một nút bấm giả lập.
```

## Tầng 2

```text
       Từ ram tầng 1 → lối chính tầng 2
                     cột 1         cột 2         cột 3
  Hàng A          [F2-A1]       [F2-A2]       [F2-A3]
                     │              │             │
  Lối đi A ─────────────────────────────────────────────→
  Hàng B          [F2-B1]       [F2-B2]       [F2-B3]
                     │              │             │
  Lối đi B ─────────────────────────────────────────────→
  Hàng C          [F2-C1]       [F2-C2]       [F2-C3]
                     │              │             │
  Lối đi C ─────────────────────────────────────────────→ ram xuống F1/cổng ra

  Tất cả 9 ô tầng 2: nút bấm giả lập.
```

## Ánh xạ 18 nút → GPIO (ESP32 thường, `slots-01`)

| Ô | GPIO | Ô | GPIO |
|---|---|---|---|
| F1-A1 | 25 | F2-A1 | 17 |
| F1-A2 | 26 | F2-A2 | 18 |
| F1-A3 | 27 | F2-A3 | 19 |
| F1-B1 | 32 | F2-B1 | 21 |
| F1-B2 | 33 | F2-B2 | 22 |
| F1-B3 | 4 | F2-B3 | 23 |
| F1-C1 | 13 | F2-C1 | 5 |
| F1-C2 | 14 | F2-C2 | 15 |
| F1-C3 | 16 | F2-C3 | 12 |

Mỗi nút một chân vào GPIO, chân kia vào GND; firmware bật pull-up trong chip (nhả = HIGH, nhấn = LOW). Chân chưa cắm nút đọc HIGH nên coi như chưa nhấn. Không cắm nút vào GPIO 0/2 (BOOT, LED), 1/3 (UART), 6–11 (flash), 34–39 (không có pull-up). Không giữ nút F2-C2/F2-C3 (GPIO 15/12, chân strapping) lúc cấp nguồn. Firmware lưu map này cố định, không suy diễn từ thứ tự topic.

## Gợi ý ô và vẽ đường đi

Hệ thống **không gán ô** cho xe; ô chỉ để chỉ chỗ trống.

1. Ô gợi ý = ô `AVAILABLE` đầu tiên theo thứ tự F1-A1…F1-C3 rồi F2-A1…F2-C3 (gần cổng trước), tính lại mỗi lần khách mở trang QR/kiosk. Không còn ô trống → "Bãi đang đầy"; board ô offline → không gợi ý, khách tự chọn.
2. Trang QR cho khách chạm chọn ô trống bất kỳ (hoặc ô `UNKNOWN` khi board offline).
3. Đường đi (web vẽ bằng SVG, email ghi bằng chữ), khớp sơ đồ trên:
   - Từ **cổng vào** (góc trái trên) đi theo **lối chính bên trái** xuống tới lối đi của hàng ô đích;
   - rẽ phải theo lối đi ngang (ngay dưới hàng ô) tới cột của ô, rồi vào ô.
   - Ô **tầng 2**: tầng 1 đi hết lối C tới **ram lên tầng 2** (ghi "đi tiếp lên tầng 2"); tầng 2 đi từ đầu ram theo lối chính bên trái như tầng 1.
4. Chỉ dẫn chữ, ví dụ:
   - `F1-B2`: "Qua cổng vào, đi theo lối chính bên trái → Rẽ phải vào lối đi hàng B → Ô F1-B2 ở cột 2, phía trên lối đi."
   - `F2-C3`: "… đến cuối lối C → Đi hết lối C, LÊN RAM lên tầng 2 → Tầng 2: … rẽ phải vào lối đi hàng C → Ô F2-C3 ở cột 3."
5. OLED dùng bản rút gọn (`VAO: goi y F1-A2`, `Con 12 cho trong`).

Sơ đồ là logic, chưa theo kích thước thật; không tuyên bố khoảng cách mét khi chưa đo bãi.
