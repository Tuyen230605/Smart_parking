# Use case và quy tắc nghiệp vụ

Tham chiếu [kiến trúc](architecture.md), [sơ đồ bãi](parking-layout.md), [MQTT](mqtt-contract.md), [API](api-contract.md). Các bước dưới đây là hợp đồng chức năng giữa nhóm phần cứng, edge, cloud và web.

## Tác nhân

- **Khách:** lái xe, có thể không cung cấp email; không cần tài khoản.
- **Quản trị:** đăng nhập, xác nhận trường hợp lỗi, thu phí thủ công, xác nhận xe qua cổng.
- **Pi vision:** phát hiện màu thẻ/biển số/làn từ một camera.
- **ESP gate:** điều khiển hai cần và OLED.
- **ESP slots:** báo 18 trạng thái ô, trong đó F1-A1 là cảm biến thật.
- **Backend:** quyết định nghiệp vụ duy nhất.

## Trạng thái phiên

```text
RESERVED → ENTRY_GATE_OPEN → PARKED                  (ACK cần vào; ô được gán báo có xe)
RESERVED / ENTRY_GATE_OPEN → EXPIRED                 (5 phút ô không báo có xe)
PARKED → EXIT_REQUESTED                              (thẻ đỏ, phí 0 ₫: NO_CHARGE)
PARKED → PAYMENT_PENDING → EXIT_REQUESTED            (thẻ đỏ, có phí: PENDING → PAID_CASH | WAIVED)
EXIT_REQUESTED → EXIT_GATE_OPEN → CLOSED             (quản trị mở cần, ACK cần ra; quản trị xác nhận xe qua)
MANUAL_REVIEW → RESOLVED | DISMISSED                 (quản trị cho vào/cho ra hoặc bỏ qua)
```

`PARKED` chỉ có sau khi ô được gán báo có xe. `CLOSED` cần thao tác xác nhận xe ra từ quản trị. Sự kiện không chắc chắn không tạo phiên thường mà tạo phiên `MANUAL_REVIEW` riêng (UC-07). Mọi chuyển trạng thái từ thiết bị gắn với `event_id` và chỉ chạy một lần; thao tác quản trị gắn với `Idempotency-Key` và ghi audit. Bảng trạng thái đầy đủ ở [api-contract.md](api-contract.md) mục 5.

## UC-01: Xe vào, có ô, không nhập email

**Điều kiện:** thẻ xanh trong vùng làn vào, OCR đủ tin cậy, không có phiên đang mở cho biển số, có ô `AVAILABLE`.

1. Pi phát `vehicle_detected` với `lane_id=ENTRY`, `card_color=GREEN`; backend chuẩn hóa biển số và chống sự kiện lặp.
2. Backend giữ ô bằng ghi có điều kiện, tạo phiên `RESERVED` và đường đi; kiosk nhận QR phiên.
3. Backend phát `gate_command` (`gate=ENTRY`, `action=OPEN`); ESP gate mở đúng cần và ACK `OPEN`, phiên sang `ENTRY_GATE_OPEN`.
4. OLED hiện `VAO: F1-A1` / `Tang 1 - Hang A` / `O so 1` (ASCII không dấu); kiosk hiển thị QR và hướng dẫn tiếng Việt.
5. Khách bỏ qua QR; không có email.
6. Khi trạng thái ô được gán thành `occupied=true`, phiên chuyển `PARKED`.

**Kết quả:** xe vào và được hướng dẫn ngay cả khi không cung cấp liên hệ.

## UC-02: Xe vào, quét QR và nhận email của lượt này

**Điều kiện:** UC-01 đã tạo phiên, token QR chưa quá 15 phút.

1. Khách quét QR phiên trên màn hình kiosk; trang `/s/{token}` trả số ô và chỉ dẫn, không hiện biển số đầy đủ.
2. Khách nhập email, đánh dấu đồng ý nhận email hướng dẫn cho **lượt này**, bấm gửi.
3. API kiểm tra token, thời hạn, định dạng email và giới hạn một lần gửi/phiên; ghi email vào phiên và gọi SES.
4. Web báo đã yêu cầu gửi; backend ghi `email_status` (`QUEUED/ACCEPTED_BY_SES/FAILED`). SES chấp nhận yêu cầu không đồng nghĩa thư đã tới inbox. Nếu gửi lỗi, khách vẫn thấy đường trên web/OLED.
5. Email bị xóa khi quản trị xác nhận xe ra; muộn nhất xóa sau 10 ngày từ lúc nhập. Gửi lại form với cùng `Idempotency-Key` (mạng chập chờn) không gửi email lần hai.

**Kết quả:** không cần đăng ký tài khoản. Lượt sau không tự gửi vào email này; khách nhập lại nếu muốn.

## UC-03: Xe quay lại sau lần trước

Backend tạo phiên và QR mới như UC-01. Không tìm email theo biển số cũ và không gửi email tự động. Nếu khách muốn nhận, thực hiện UC-02 một lần nữa. Sự kiện/biển số cũ đã xóa sau tối đa 10 ngày.

## UC-04: Bãi đầy hoặc ô không đáng tin

Backend chỉ tính các ô `AVAILABLE` có dữ liệu mới. Nếu không còn ô: không tạo phiên, không mở cần vào, OLED màn `LOT_FULL` hiện `BAI DA DAY`. Nếu ESP slots quá 90 giây không gửi snapshot, tất cả ô do board đó quản lý thành `UNKNOWN`; xe vào lúc đó thành `MANUAL_REVIEW` (`SLOTS_UNKNOWN`), không gán trên dữ liệu cũ.

## UC-05: Xe không vào ô được gán

Job chạy mỗi phút: phiên `RESERVED`/`ENTRY_GATE_OPEN` quá 5 phút mà ô chưa báo có xe chuyển `EXPIRED`, bỏ khóa biển số và QR, giải phóng ô chỉ khi ô vẫn trống. Dashboard báo số lượt hết hạn trong 1 giờ qua. Nếu một ô khác báo có xe, không tự gán lại; dashboard báo "ô có xe nhưng không có phiên" để quản trị kiểm tra.

## UC-06: Xe yêu cầu ra và tính phí

**Điều kiện:** thẻ đỏ ở vùng làn ra, OCR đủ tin cậy, tìm đúng một phiên `PARKED`.

1. Pi phát `vehicle_detected` với `lane_id=EXIT`, `card_color=RED`; backend tìm phiên còn mở theo biển số.
2. Backend đặt `charge_end_at` = lúc nhận sự kiện và tính phí theo bảng giá đã chép lúc xe vào: miễn phí dưới 15 phút; đến 60 phút 10.000 ₫; mỗi giờ tiếp theo bắt đầu +5.000 ₫. Mức này chỉ là ví dụ demo, quản trị sửa được.
3. OLED cổng ra hiện phí (không hiện biển số); web quản trị hiện phí và biển số.
4. Phí 0 ₫: phiên `EXIT_REQUESTED`, `payment_status=NO_CHARGE`. Có phí: phiên `PAYMENT_PENDING`, `payment_status=PENDING`; quản trị thu tiền và ghi `PAID_CASH` (đúng số tiền đã chốt) hoặc `WAIVED` (bắt buộc ghi chú), phiên về `EXIT_REQUESTED`.
5. Quản trị bấm mở cần ra; backend chỉ phát lệnh khi gate-01 online; ESP ACK `OPEN`, phiên `EXIT_GATE_OPEN`. G3 chưa chốt: phiên 0 ₫ vẫn chờ quản trị bấm.
6. Quản trị xác nhận xe đã qua; backend ghi `exit_confirmed_at`, đóng phiên, bỏ khóa biển số và xóa email. Tiền đã khóa ở bước 2, không tăng trong lúc khách thanh toán.
7. Ô được giải phóng chỉ khi ESP slots báo trống. Nếu chưa, dashboard báo ô có xe mà không có phiên.

**Kết quả:** có phiếu tính phí trong admin; không có thanh toán online thật.

## UC-07: OCR kém, sai làn, thẻ không hợp lệ

- `plate_confidence` dưới ngưỡng cấu hình, không thấy biển số, thẻ xanh ở làn ra, thẻ đỏ ở làn vào hoặc hai xe xuất hiện cùng khung → `MANUAL_REVIEW`. Backend ghi `review_reason` (bảng ở [mqtt-contract.md](mqtt-contract.md) mục 3), gồm cả sự kiện đến trễ, biển số đang có phiên, dữ liệu ô cũ, xe ra mà không có phiên đang đỗ.
- Không mở cần tự động; OLED hiện `CHO NHAN VIEN`. Quản trị xem OCR gốc, nhập biển số đúng và chọn một trong ba, bắt buộc ghi lý do:
  - **Cho vào:** tạo phiên `RESERVED` mới như UC-01, mở cần vào.
  - **Cho ra:** chốt phí cho phiên đang ở bãi của biển số đó, tính đến lúc xe tới cổng ra, rồi tiếp UC-06 bước 4.
  - **Bỏ qua:** phiên chờ xử lý thành `DISMISSED`, không tác dụng phụ.
- Một camera không đủ độ phân giải cho cả hai làn thì chạy demo theo từng làn hoặc đổi góc camera, không giả lập OCR đúng.

## UC-08: Nút giả lập và cảm biến thật

F1-A1 dùng một cảm biến ToF thật. 17 ô khác có một nút riêng/ô. Mỗi nhấn hợp lệ (debounce khoảng 50 ms) đảo `occupied`; nhấn tiếp đảo lại. ESP lưu trạng thái nút vào NVS, gửi `slot_changed` ngay và `slots_snapshot` mỗi 30 giây/khởi động lại. Web gắn nhãn “cảm biến” hoặc “mô phỏng” để không nhầm.

## UC-09: Sự cố kết nối/lệnh trùng

- MQTT QoS 1 có thể phát lại; backend chống trùng `event_id`, ESP chống trùng `command_id`.
- Lệnh cần chắn hết hạn hoặc không đúng `target` bị bỏ qua và ACK lỗi.
- Mất AWS/Wi-Fi: ESP không nhận lệnh mới; không tự mở cần. OLED hiện “Mất kết nối”; quản trị thao tác thủ công tại mô hình sau khi kiểm tra cơ cấu.
- Servo không ACK → phiên giữ trạng thái trước đó, trang quản trị hiện "đang chờ gate-01 báo cần đã mở"; không suy luận xe đã qua. ESP báo `ERROR` → lỗi hiện trên phiên và dashboard. (Cảnh báo tự động khi quá hạn ACK chưa làm.)
- gate-01 offline quá 90 giây → API không cho mở cần ra (`503 DEVICE_OFFLINE`).
- Email SES lỗi → ghi trạng thái thất bại, không rollback việc gán ô.

## UC-10: Xóa dữ liệu sau 10 ngày

Biển số, email, token và sự kiện có thể nhận dạng được từ mỗi lần thu thập có `identity_expires_at = collected_at + 10 days`. API ngừng trả dữ liệu quá hạn ngay tại mốc này; job purge theo giờ xóa từ mốc 9 ngày 23 giờ (biển số, email, nonce QR, khóa `ActivePlates`) và alarm báo khi job lỗi; DynamoDB TTL chỉ dọn dấu sự kiện đã xử lý. Báo cáo doanh thu chỉ còn số tiền, thời gian và ID vô danh. Phiên còn mở đến sát hạn vẫn bị xóa biển số đúng hạn; dashboard cảnh báo trước 24 giờ để quản trị đóng/xử lý thủ công, không kéo dài thời gian giữ biển số.

## Bảng kiểm nghiệm thu

| Mã | Kết quả phải thấy |
|---|---|
| UC-01 | Có QR và OLED chỉ ô, không có email |
| UC-02 | Khách nhập email một lần, nhận đúng hướng dẫn phiên |
| UC-03 | Lượt mới không tự dùng email cũ |
| UC-04 | Bãi đầy/dữ liệu ô cũ không mở cần |
| UC-05 | Giữ ô hết hạn được giải phóng có điều kiện |
| UC-06 | Phí được tính và có xác nhận thu tiền/xe qua cổng |
| UC-07 | OCR/sai làn chuyển duyệt thủ công |
| UC-08 | Một ô sensor, 17 ô nút; trạng thái đúng sau restart |
| UC-09 | Replay/mất mạng không gây mở cần trùng |
| UC-10 | Dữ liệu định danh quá 10 ngày không còn truy cập được |
