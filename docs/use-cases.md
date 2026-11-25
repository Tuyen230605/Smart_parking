# Use case và quy tắc nghiệp vụ

Tham chiếu [kiến trúc](architecture.md), [sơ đồ bãi](parking-layout.md), [MQTT](mqtt-contract.md), [API](api-contract.md). Các bước dưới đây là hợp đồng chức năng giữa nhóm phần cứng, edge, cloud và web.

## Tác nhân

- **Khách:** lái xe, có thể không cung cấp email; không cần tài khoản.
- **Quản trị:** đăng nhập, bấm *Cho vào* / *Cho ra* (mở cần), thu phí thủ công.
- **Pi vision:** phát hiện có vật (tay/xe mô hình) ở vùng làn vào/ra từ một camera; không đọc biển.
- **ESP gate:** một servo 3 vị trí (thẳng = đóng, trái = mở vào, phải = mở ra) và OLED.
- **ESP slots:** báo 18 trạng thái ô, mỗi ô một nút bấm; chỉ để chỉ chỗ trống.
- **Backend:** quyết định nghiệp vụ duy nhất; đánh biển số demo; nguồn duy nhất của danh sách xe trong bãi.

## Trạng thái phiên

```text
camera thấy xe ở làn VÀO → ENTRY_PENDING ──(quản trị: Cho vào → mở cần vào)──→ PARKED
                                          └─(quản trị: Không cho vào)─────────→ REJECTED
camera thấy xe ở làn RA  → PARKED → EXIT_REQUESTED (khóa phí)
                         ──(quản trị: Cho ra / Đã thu tiền → mở cần ra)──→ CLOSED
```

Xe nằm trong **danh sách xe trong bãi** khi phiên ở `PARKED` hoặc `EXIT_REQUESTED`. Danh sách hiện ở web (Quản trị → Tổng quan) và trang camera trên Pi, chỉ đổi sau khi quản trị bấm. Mọi sự kiện có `event_id` và chỉ xử lý một lần. Nút ô không làm đổi trạng thái phiên.

## Biển số demo

Pi không đọc biển. Khi có xe ở làn vào, backend đặt biển là **số nhỏ nhất chưa dùng** bởi xe trong bãi hoặc xe đang chờ vào: chưa có xe → `11111`; đã có `11111`, `22222` → `33333`. Từ xe thứ 10 lặp số 3 lần (`101010`) để không trùng. Khi có xe ở làn ra, backend chọn xe **số lớn nhất** đang đỗ (chưa yêu cầu ra). Nếu Pi gửi biển đọc được với độ tin cậy đủ ngưỡng thì backend dùng biển đó.

## UC-01: Xe vào, không nhập email

**Điều kiện:** Pi thấy vật ở vùng làn vào; bãi chưa đầy (hoặc board ô offline).

1. Pi phát `vehicle_detected` (`lane_id=ENTRY`, không biển số); backend chống sự kiện lặp, đánh biển demo, tạo phiên `ENTRY_PENDING`. OLED hiện `XE 11111 / Cho nhan vien`.
2. Trang Phiên đỗ hiện thẻ "Chờ cho vào" với biển số; trang camera Pi hiện "Chờ cho vào: 11111".
3. Quản trị bấm **Cho vào (mở cần vào)** → phiên `PARKED`, backend phát `OPEN ENTRY`; servo quay trái, sau 5 giây tự về giữa.
4. OLED hiện ô trống gợi ý (`VAO: goi y F1-A2`, `Con N cho trong`); kiosk hiển thị QR kèm bản đồ đường đi.
5. Xe vào danh sách xe trong bãi. Khách bỏ qua QR; không có email.

Quản trị bấm **Không cho vào** → phiên `REJECTED`, số biển được dùng lại cho xe sau.

## UC-02: Quét QR, chọn ô, nhận email

**Điều kiện:** UC-01 đã cho vào, token QR chưa quá 15 phút.

1. Khách quét QR trên kiosk; trang `/s/{token}` hiện ô trống gần cổng nhất (gợi ý), bản đồ hai tầng và đường đi vẽ từ cổng vào. Không hiện biển số.
2. Khách **chạm một ô trống khác** để chọn; đường đi vẽ lại. Ô tầng 2: bản đồ tầng 1 vẽ tới ram, ghi "đi tiếp lên tầng 2", bản đồ tầng 2 vẽ từ đầu ram tới ô.
3. Khách nhập email, đồng ý nhận email cho lượt này, bấm gửi. Email ghi đường tới ô đã chọn và link mở lại bản đồ.
4. API giới hạn một lần gửi/phiên; ghi `email_status` (`QUEUED/ACCEPTED_BY_SES/FAILED`). SES lỗi không ảnh hưởng việc xe vào.

Gợi ý/chọn ô chỉ là chỉ đường: ô không bị giữ, xe khác vẫn có thể đỗ vào.

## UC-03: Ghi nhớ email cho biển số (khách tự chọn)

1. Ở bước 3 của UC-02, khách tích **"Ghi nhớ email cho biển số xe này"** (mặc định không tích).
2. Lần sau xe có biển đó được *Cho vào*, backend **tự gửi email chỉ dẫn** (ô gợi ý + link bản đồ), không cần quét QR; trang QR báo "đã tự gửi".
3. Mỗi email tự gửi có link **Hủy liên kết**; trang QR hiện email đã che (`kh***@gmail.com`) và nút **Bỏ liên kết email**.
4. Không tích thì email chỉ dùng cho lượt đó và bị xóa muộn nhất sau 10 ngày.

**Lưu ý demo:** biển demo được dùng lại cho xe sau, nên bỏ liên kết sau khi thử.

## UC-04: Bãi đầy hoặc board ô mất kết nối

Khi quản trị bấm *Cho vào* mà board ô đang online và không còn ô `AVAILABLE` → báo "Bãi đã đầy", không mở cần, OLED hiện "BAI DA DAY". Nếu ESP slots mất kết nối quá 90 giây, mọi ô thành `UNKNOWN`; xe vẫn được cho vào nhưng không có ô gợi ý (khách vẫn chọn được ô trên bản đồ).

## UC-05: Xe ra và tính phí

1. Pi thấy vật ở vùng làn ra → backend chọn xe số lớn nhất đang đỗ, đặt `charge_end_at` và tính phí: miễn phí dưới 15 phút; đến 60 phút 10.000 ₫; mỗi giờ tiếp theo bắt đầu +5.000 ₫ (ví dụ demo). Phiên sang `EXIT_REQUESTED`.
2. Trang Phiên đỗ hiện thẻ "Chờ cho ra" với **phí chữ lớn**; OLED cổng hiện phí. Cần ra **không tự mở**, kể cả miễn phí.
3. Phí 0 ₫ → quản trị bấm **Cho ra (mở cần)**. Có phí → bấm **Đã thu X ₫ → cho ra** (`PAID_CASH`) hoặc **Miễn phí** có lý do (`WAIVED`).
4. Backend phát `OPEN EXIT` (servo quay phải), phiên `CLOSED` ngay, xe rời danh sách xe trong bãi. Phí đã khóa ở bước 1, không tăng trong lúc thu tiền.
5. Ô về trống khi nút ô được bấm lại.

Bãi không còn xe đang đỗ mà Pi báo xe ra → bỏ qua (`NO_CAR`).

## UC-06: Sự kiện bất thường

- Thẻ/làn không hợp lệ (Pi gửi sai cặp làn–màu) → bỏ qua, ghi log. Không còn hàng "chờ duyệt" riêng.
- Camera báo lặp khi tay vẫn trong khung → Pi chỉ báo một lần, phải rút tay ra mới nhận lượt mới; lượt thừa thì quản trị bấm *Không cho vào*.

## UC-07: Trang camera trên Pi

`http://<ip-pi>:8000` hiện video, hai khung làn, danh sách xe trong bãi / chờ vào / chờ ra (backend gửi qua MQTT), nút **Thử xe VÀO / Thử xe RA** (giả lập khi chưa chỉnh camera) và **Chụp lại nền**.

## UC-08: Nút giả lập

Mỗi ô trong 18 ô có một nút riêng. Mỗi nhấn hợp lệ (debounce khoảng 50 ms) đảo `occupied`; nhấn tiếp đảo lại. ESP lưu trạng thái nút vào NVS, gửi `slot_changed` ngay và `slots_snapshot` mỗi 30 giây/khởi động lại. Web ghi rõ các ô là nút mô phỏng.

## UC-09: Sự cố kết nối/lệnh trùng

- MQTT QoS 1 có thể phát lại; backend chống trùng `event_id`, ESP chống trùng `command_id`.
- Lệnh cần chắn hết hạn hoặc không đúng `target` bị bỏ qua và ACK lỗi.
- Mất AWS/Wi-Fi: ESP không nhận lệnh mới; không tự mở cần. OLED hiện “Mất kết nối”; quản trị thao tác thủ công tại mô hình sau khi kiểm tra cơ cấu.
- Servo không ACK mở/đóng đúng hạn → backend cảnh báo, không suy luận xe đã qua.
- Email SES lỗi → ghi trạng thái thất bại, không ảnh hưởng việc cho xe vào.

## UC-10: Xóa dữ liệu sau 10 ngày

Biển số, email, token và sự kiện có thể nhận dạng được từ mỗi lần thu thập có `identity_expires_at = collected_at + 10 days`. API ngừng trả dữ liệu quá hạn ngay tại mốc này; job purge theo giờ chọn xóa từ mốc 9 ngày 23 giờ và cảnh báo khi lỗi, DynamoDB TTL hỗ trợ dọn nền. Báo cáo doanh thu chỉ còn số tiền, thời gian và ID vô danh. Nếu phiên còn mở đến sát hạn, quản trị cần đóng/xử lý thủ công; không kéo dài thời gian giữ biển số.

## Bảng kiểm nghiệm thu

| Mã | Kết quả phải thấy |
|---|---|
| UC-01 | Xe vào chờ quản trị; bấm Cho vào thì servo quay trái, xe vào danh sách, kiosk có QR |
| UC-02 | Chọn ô trên bản đồ, đường đi vẽ đúng (tầng 2 có lên ram); email đúng ô đã chọn |
| UC-03 | Tích ghi nhớ → lần sau tự gửi email; hủy liên kết thì không gửi nữa |
| UC-04 | Bãi đầy không mở cần; board ô offline vẫn cho vào |
| UC-05 | Xe ra hiện phí, chỉ mở cần khi bấm Cho ra; xe rời danh sách |
| UC-06 | Sự kiện sai/lặp không tạo mở cần |
| UC-07 | Trang camera hiện đúng danh sách như web |
| UC-08 | 18 nút; trạng thái đúng sau restart |
| UC-09 | Replay/mất mạng không gây mở cần trùng |
| UC-10 | Dữ liệu định danh quá 10 ngày không còn truy cập được |
