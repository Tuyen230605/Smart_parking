# Sơ đồ mô hình bãi xe: 2 tầng, mỗi tầng 3 × 3 ô

Đây là sơ đồ logic để bố trí mô hình và tính đường đi; kích thước thật của mô hình cần đo sau khi làm mặt bãi. ID ô được dùng thống nhất trong MQTT, API, web, OLED và email.

## Quy ước

- `F1` = tầng 1, `F2` = tầng 2; `A/B/C` = hàng gần đến xa; `1/2/3` = cột từ trái sang phải.
- Có **18 ô**, một cảm biến thật ở `F1-A1`, 17 ô còn lại do nút bấm giả lập.
- Hai làn vào/ra riêng và hai cần chắn riêng, cùng nằm trong góc nhìn camera Pi.
- Mũi tên thể hiện chiều xe đi trong mô hình. Đường lên tầng 2 là ram dốc tượng trưng; phần cứng có thể là hai mặt bãi xếp tầng.

## Cổng và làn

```text
                          [1 CAMERA + PI 5]
                    ROI vào             ROI ra
                       ↓                   ↓
       Đường đến  ──> [THẺ XANH]       [THẺ ĐỎ] <── Đường ra
                        │                   │
                  [CẦN VÀO]            [CẦN RA]
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

**Lưu ý:** một OLED dùng chung cần ưu tiên thông báo sự kiện mới nhất và ghi rõ `VÀO`/`RA`; nếu hai làn hoạt động đồng thời, kiosk/web vẫn hiển thị thông tin theo phiên. Camera chỉ phát sự kiện khi màu thẻ nằm trong đúng ROI và thấy một biển số phù hợp.

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

  * F1-A1: cảm biến thật; 8 ô còn lại: nút bấm giả lập.
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

## Ánh xạ 18 input

| Input | Ô | Kiểu | Input | Ô | Kiểu |
|---|---|---|---|---|---|
| S0 | F1-A1 | ToF thật | B9 | F2-A1 | Nút |
| B1 | F1-A2 | Nút | B10 | F2-A2 | Nút |
| B2 | F1-A3 | Nút | B11 | F2-A3 | Nút |
| B3 | F1-B1 | Nút | B12 | F2-B1 | Nút |
| B4 | F1-B2 | Nút | B13 | F2-B2 | Nút |
| B5 | F1-B3 | Nút | B14 | F2-B3 | Nút |
| B6 | F1-C1 | Nút | B15 | F2-C1 | Nút |
| B7 | F1-C2 | Nút | B16 | F2-C2 | Nút |
| B8 | F1-C3 | Nút | B17 | F2-C3 | Nút |

Hai MCP23017 trên ESP slots mở rộng 32 GPIO (địa chỉ I²C ví dụ 0x20 và 0x21). Chỉ dùng 17 input đầu tiên; mỗi nút kéo xuống GND, bật pull-up. ToF I²C ở địa chỉ khác (ví dụ 0x29). Firmware lưu map này cố định trong cấu hình, không suy diễn từ thứ tự topic.

## Quy tắc chọn ô và chỉ đường

1. Loại `OCCUPIED`, `RESERVED`, `UNKNOWN`, `OUT_OF_SERVICE`.
2. Chọn ô có tổng trọng số đường đi nhỏ nhất từ cổng vào. MVP dùng thứ tự F1-A1…F1-C3 rồi F2-A1…F2-C3, tương đương độ ưu tiên theo vị trí trong mô hình.
3. Khi bằng điểm, chọn ID ô nhỏ hơn để kết quả ổn định.
4. Sinh chỉ dẫn từ `floor,row,column`, ví dụ:
   - `F1-B2`: “Tầng 1, đi thẳng đến hàng B, ô số 2.”
   - `F2-C3`: “Lên ram tầng 2, đi đến hàng C, ô số 3.”
5. OLED dùng bản rút gọn; web/email dùng đầy đủ và tô sáng ô trên sơ đồ.

Đồ thị đường đi chi tiết có thể thêm sau khi đo kích thước bãi. Không tuyên bố khoảng cách mét khi chưa có kích thước thật.
