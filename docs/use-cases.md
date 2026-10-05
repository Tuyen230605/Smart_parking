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
DETECTED → RESERVED → ENTRY_GATE_OPEN → PARKED
                                  ↘ EXPIRED (không vào ô)
PARKED → EXIT_REQUESTED → PAYMENT_PENDING → EXIT_GATE_OPEN
       → EXIT_CONFIRMED → CLOSED
DETECTED/EXIT_REQUESTED → MANUAL_REVIEW (OCR, lane hoặc thiết bị không chắc chắn)
```

`PARKED` chỉ có sau khi ô được gán báo có xe. `CLOSED` cần thao tác xác nhận xe ra từ quản trị. Mọi chuyển trạng thái phải có `event_id` và chỉ chạy một lần.

## UC-01: Xe vào, có ô, không nhập email

**Điều kiện:** thẻ xanh trong vùng làn vào, OCR đủ tin cậy, không có phiên đang mở cho biển số, có ô `AVAILABLE`.

1. Pi phát `entry_detected`; backend chuẩn hóa biển số và chống sự kiện lặp.
2. Backend giữ ô bằng ghi có điều kiện, tạo phiên và đường đi; kiosk nhận QR phiên.
3. Backend phát `open` cho `entry`; ESP gate mở đúng cần và ACK.
4. OLED hiện `F1-A1 | Tầng 1 | Hàng A | Ô 1`; kiosk hiển thị QR và hướng dẫn.
5. Khách bỏ qua QR; không có email.
6. Khi trạng thái ô được gán thành `occupied=true`, phiên chuyển `PARKED`.

**Kết quả:** xe vào và được hướng dẫn ngay cả khi không cung cấp liên hệ.

## UC-02: Xe vào, quét QR và nhận email của lượt này

**Điều kiện:** UC-01 đã tạo phiên, token QR chưa quá 15 phút.

1. Khách quét QR phiên trên màn hình kiosk; trang `/s/{token}` trả số ô và chỉ dẫn, không hiện biển số đầy đủ.
2. Khách nhập email, đánh dấu đồng ý nhận email hướng dẫn cho **lượt này**, bấm gửi.
3. API kiểm tra token, thời hạn, định dạng email và giới hạn một lần gửi/phiên; ghi email vào phiên và gọi SES.
4. Web báo đã yêu cầu gửi; backend ghi `email_status` (`QUEUED/ACCEPTED_BY_SES/FAILED`). SES chấp nhận yêu cầu không đồng nghĩa thư đã tới inbox. Nếu gửi lỗi, khách vẫn thấy đường trên web/OLED.
5. Khi phiên kết thúc, email có thể xóa ngay; muộn nhất xóa sau 10 ngày từ lúc nhập.

**Kết quả:** không cần đăng ký tài khoản. Lượt sau không tự gửi vào email này; khách nhập lại nếu muốn.

## UC-03: Xe quay lại sau lần trước

Backend tạo phiên và QR mới như UC-01. Không tìm email theo biển số cũ và không gửi email tự động. Nếu khách muốn nhận, thực hiện UC-02 một lần nữa. Sự kiện/biển số cũ đã xóa sau tối đa 10 ngày.

## UC-04: Bãi đầy hoặc ô không đáng tin

Backend chỉ tính các ô `AVAILABLE` có dữ liệu mới. Nếu không còn ô, trả `LOT_FULL`; không mở cần vào, OLED/kiosk hiện “Bãi đầy”. Nếu ESP slots mất kết nối quá 90 giây, tất cả ô do board đó quản lý thành `UNKNOWN`; không gán trên dữ liệu cũ.

## UC-05: Xe không vào ô được gán

Sau 5 phút `RESERVED` mà ô chưa báo có xe, backend chuyển `EXPIRED`, giải phóng ô chỉ khi trạng thái vẫn trống và báo quản trị. Nếu một ô khác báo có xe, không tự gán lại; quản trị kiểm tra rồi sửa phiên bằng thao tác có log.

## UC-06: Xe yêu cầu ra và tính phí

**Điều kiện:** thẻ đỏ ở vùng làn ra, OCR đủ tin cậy, tìm đúng một phiên `PARKED`.

1. Pi phát `exit_requested`; backend tìm phiên còn mở theo biển số.
2. Backend đặt `charge_end_at = exit_requested_at` và tính phí của lượt theo cấu hình giá: miễn phí dưới 15 phút; đến 60 phút 10.000 ₫; mỗi giờ tiếp theo bắt đầu +5.000 ₫. Mức này chỉ là ví dụ demo.
3. OLED cổng ra và web quản trị hiện phí, biển số được che một phần ở màn hình công khai.
4. Nếu phí 0 ₫, trạng thái là `NO_CHARGE`; nếu có phí, quản trị thu tiền và bấm `PAID_CASH`, hoặc `WAIVED` có lý do. Backend phát lệnh mở cần ra; ESP gate ACK.
5. Quản trị xác nhận xe đã qua; backend ghi `exit_confirmed_at` và đóng phiên. Tiền đã khóa ở bước 2, không tăng trong lúc khách thanh toán.
6. Ô được giải phóng chỉ khi ESP slots báo trống. Nếu chưa, web báo bất nhất.

**Kết quả:** có phiếu tính phí trong admin; không có thanh toán online thật.

## UC-07: OCR kém, sai làn, thẻ không hợp lệ

- `plate_confidence` dưới ngưỡng cấu hình, không thấy biển số, thẻ xanh ở làn ra, thẻ đỏ ở làn vào hoặc hai xe xuất hiện cùng khung → `MANUAL_REVIEW`.
- Không mở cần tự động. Quản trị xem thông tin tối thiểu, nhập/đính chính biển số và chọn cho vào/ra bằng thao tác có log.
- Một camera không đủ độ phân giải cho cả hai làn thì chạy demo theo từng làn hoặc đổi góc camera, không giả lập OCR đúng.

## UC-08: Nút giả lập và cảm biến thật

F1-A1 dùng một cảm biến ToF thật. 17 ô khác có một nút riêng/ô. Mỗi nhấn hợp lệ (debounce khoảng 50 ms) đảo `occupied`; nhấn tiếp đảo lại. ESP lưu trạng thái nút vào NVS, gửi `slot_changed` ngay và `slots_snapshot` mỗi 30 giây/khởi động lại. Web gắn nhãn “cảm biến” hoặc “mô phỏng” để không nhầm.

## UC-09: Sự cố kết nối/lệnh trùng

- MQTT QoS 1 có thể phát lại; backend chống trùng `event_id`, ESP chống trùng `command_id`.
- Lệnh cần chắn hết hạn hoặc không đúng `target` bị bỏ qua và ACK lỗi.
- Mất AWS/Wi-Fi: ESP không nhận lệnh mới; không tự mở cần. OLED hiện “Mất kết nối”; quản trị thao tác thủ công tại mô hình sau khi kiểm tra cơ cấu.
- Servo không ACK mở/đóng đúng hạn → backend cảnh báo, không suy luận xe đã qua.
- Email SES lỗi → ghi trạng thái thất bại, không rollback việc gán ô.

## UC-10: Xóa dữ liệu sau 10 ngày

Biển số, email, token và sự kiện có thể nhận dạng được từ mỗi lần thu thập có `identity_expires_at = collected_at + 10 days`. API ngừng trả dữ liệu quá hạn ngay tại mốc này; job purge theo giờ chọn xóa từ mốc 9 ngày 23 giờ và cảnh báo khi lỗi, DynamoDB TTL hỗ trợ dọn nền. Báo cáo doanh thu chỉ còn số tiền, thời gian và ID vô danh. Nếu phiên còn mở đến sát hạn, quản trị cần đóng/xử lý thủ công; không kéo dài thời gian giữ biển số.

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
