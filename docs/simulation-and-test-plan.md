# Kế hoạch mô phỏng và tích hợp

## Mục đích

Kiểm tra hợp đồng message và nghiệp vụ vào/ra/gán ô trước khi nhóm có đủ phần cứng. Mô phỏng không thay thế kiểm tra điện, hành trình cơ khí và an toàn của cần chắn.

## Các mức mô phỏng

1. **Unit:** kiểm thử logic phân loại màu, parser biển số, debounce cảm biến, chọn ô và chuyển trạng thái phiên đỗ bằng fixture.
2. **Device mock:** script giả lập Pi/ESP32 publish-subscribe MQTT; cho phép cấu hình biển số, trạng thái ô, độ trễ, mất kết nối và confidence.
3. **System integration:** backend, broker local hoặc AWS dev IoT, database dev và dashboard cùng chạy một kịch bản đầu-cuối.
4. **Hardware-in-the-loop:** thay mock bằng camera/Pi/ESP32 thật; bắt đầu bằng servo không tải và kiểm tra hành trình trước khi gắn cần.

## Máy trạng thái nghiệp vụ

```text
ARRIVAL_DETECTED -> VALIDATING -> SLOT_ASSIGNED -> GATE_OPEN_REQUESTED
 -> ENTERED_WAITING_FOR_SLOT -> PARKED -> EXIT_REQUESTED -> EXIT_CONFIRMED -> CLOSED
```

Nhánh xử lý: `VALIDATION_REQUIRED` khi OCR thấp; `FULL` khi hết chỗ; `ERROR` khi thiết bị/cảm biến lỗi; `EXPIRED` khi xe không đến trong khoảng thời gian đặt trước.

## Kịch bản chấp nhận

| ID | Điều kiện | Hành động | Tiêu chí đạt |
|---|---|---|---|
| SIM-01 | Có ít nhất một ô trống | Gửi xe vào hợp lệ | Chọn đúng một ô, cần vào nhận một lệnh, thông báo có ô và hướng dẫn |
| SIM-02 | Không còn ô | Gửi xe vào | Không gán ô; không phát lệnh mở tự động; lưu lý do bãi đầy |
| SIM-03 | Có phiên đỗ theo biển số | Gửi yêu cầu xe ra | Tìm đúng phiên, mở cần ra, đóng phiên sau xác nhận |
| SIM-04 | OCR thấp | Gửi sự kiện vào/ra | Chuyển xác nhận thủ công, không ghép nhầm xe |
| SIM-05 | Message gửi lại cùng ID | Replay event/command | Không tạo phiên trùng hoặc thực hiện lệnh trùng |
| SIM-06 | Cảm biến đảo trạng thái nhanh | Phát occupied/empty xen kẽ | Debounce giữ trạng thái ổn định; backend ghi nhận dữ liệu cuối hợp lệ |
| SIM-07 | Mất Wi-Fi/MQTT | Ngắt broker rồi nối lại | Thiết bị báo offline/reconnect; lệnh cũ hết hạn không được thực hiện |
| SIM-08 | Ô vừa được xe khác nhận | Gửi hai yêu cầu đồng thời | Transaction/lock chỉ cho tối đa một xe nhận cùng một ô |

## Chỉ số demo nên ghi lại

- Tỷ lệ phát hiện đúng xanh/đỏ và tỷ lệ OCR đúng trên bộ ảnh/video của nhóm.
- Thời gian từ nhận diện đến phản hồi gán ô; thời gian từ lệnh đến xác nhận cần.
- Độ trễ cập nhật ô và tỷ lệ false occupied/false empty.
- Số trường hợp xử lý đúng khi replay, mất kết nối, dữ liệu stale hoặc OCR thấp.

## Bàn giao giữa thành viên

- Pi và mock dùng cùng payload sự kiện trong `mqtt-contract.md`.
- Hai firmware dùng cùng quy ước `device_id`, timestamp, ID lệnh và mã lỗi.
- Backend cung cấp mock endpoint/fixture để frontend và nhóm cảm biến phát triển độc lập.
- Mỗi bản demo có cấu hình chạy, ảnh/video fixture được phép chia sẻ, và hướng dẫn reset trạng thái.
