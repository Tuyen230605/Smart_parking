# Mô phỏng và nghiệm thu đầu cuối

Mục tiêu là dựng đủ hành vi của **18 ô với một cảm biến thật và 17 nút**, hai làn qua một camera và hai cần qua một ESP32. Kịch bản liên kết với [use case](use-cases.md); payload lấy từ [MQTT contract](mqtt-contract.md) và [API contract](api-contract.md).

## 1. Các chế độ chạy

| Chế độ | Thiết bị | Mục đích |
|---|---|---|
| Mock local | Script thay Pi/gate/slots, broker MQTT local | Phát triển backend/web không cần sa bàn/AWS |
| AWS dev | Mock device hoặc một số thiết bị thật → IoT Core | Chốt certificate, topic, IoT Rule và Lambda |
| Sa bàn đầy đủ | Pi/camera, ESP gate/servo/OLED, ESP slots/ToF/nút | Nghiệm thu hành vi phần cứng, email và web |

Mock phải phát **cùng schema v1** và **cùng device_id** như thiết bị thật; không làm API riêng cho demo. Có thể dùng biển số giả trong fixture để không cần dữ liệu thật.

## 2. Bố trí đầu vào

- Dán hai vùng ROI `ENTRY` và `EXIT` trên mặt bãi trước camera. Thẻ xanh chỉ ở vùng vào, thẻ đỏ chỉ ở vùng ra.
- F1-A1 có xe mô hình đặt/nhấc khỏi cảm biến ToF.
- 17 nút dán nhãn B1…B17 theo bảng ở [parking-layout.md](parking-layout.md). Một nhấn đảo trạng thái; LED/sơ đồ web thể hiện trạng thái sau debounce.
- Kiosk là laptop/tablet hiện QR động; OLED hiện chỉ dẫn/phí ngắn. Màn hình admin trên cùng web app nhưng tài khoản `ADMIN`.

## 3. Kịch bản nghiệm thu

| ID | Thiết lập và thao tác | Điều kiện đạt |
|---|---|---|
| SIM-01 | Thẻ xanh, biển số giả rõ, còn F1-A1 | Tạo đúng một phiên; giữ F1-A1; cần vào mở; OLED/kiosk chỉ F1-A1 |
| SIM-02 | Quét QR, không nhập email | Web hiển thị lộ trình; không gọi SES |
| SIM-03 | Quét QR, nhập email hợp lệ và đồng ý | SES chấp nhận một email của đúng phiên; gửi lặp bị chặn; lượt sau không tự dùng email cũ |
| SIM-04 | Đặt xe trên ToF F1-A1 | F1-A1 chuyển `OCCUPIED`, phiên chuyển `PARKED`, nguồn hiện “sensor” |
| SIM-05 | Bấm B1 rồi bấm lại | F1-A2 lần lượt có xe/trống, nguồn “button”; sau reset vẫn đúng trạng thái đã lưu NVS |
| SIM-06 | Bấm 17 nút thành occupied, F1-A1 cũng occupied | Báo bãi đầy, không mở cần vào |
| SIM-07 | Thẻ đỏ đúng làn, có phiên đỗ | Hiện phí dự kiến; quản trị ghi thu tiền; chỉ cần ra mở; xác nhận qua cổng mới đóng phiên |
| SIM-08 | OCR thấp hoặc màu thẻ sai làn | `MANUAL_REVIEW`, không mở cần tự động |
| SIM-09 | Hai xe cùng tranh một ô | Ghi điều kiện chỉ giữ cho một phiên, phiên kia thử ô kế tiếp |
| SIM-10 | Replay cùng `event_id`/`command_id` | Không thêm phiên, gửi email hoặc chạy servo lần hai |
| SIM-11 | Ngắt ESP slots > 90 giây | Các ô chuyển `UNKNOWN`, backend không gán dựa trên snapshot cũ |
| SIM-12 | Ngắt Wi-Fi ESP gate, phát lệnh cũ rồi nối lại | Lệnh đã quá hạn bị bỏ; servo không mở |
| SIM-13 | Không đến ô được giữ trong 5 phút | Phiên hết hạn; ô giải phóng khi cảm biến vẫn trống |
| SIM-14 | SES lỗi hoặc sandbox chặn email | Web vẫn chỉ đường; admin thấy `FAILED`; không rollback phiên |
| SIM-15 | Token QR hết 15 phút hoặc dùng lại để gửi email | Trả `410 TOKEN_EXPIRED` hoặc `409 EMAIL_ALREADY_SENT` |
| SIM-16 | Dữ liệu định danh đã đến hạn 10 ngày | API không trả biển số/email/token, job purge dọn dữ liệu |

## 4. Số liệu nên báo cáo

- Tỷ lệ đúng màu thẻ và biển số trên tập ảnh/video giả lập đủ sáng, thiếu sáng, hai góc làn. Ghi số mẫu và cách tính; không chỉ báo phần trăm.
- Độ trễ từ Pi event đến gán ô, đến OLED/kiosk, đến ESP ACK; đo trung vị và lớn nhất trên nhiều lượt.
- Tỷ lệ phát hiện đúng của ToF F1-A1 trong các lần đặt/nhấc xe; số lần nút bounce gây đổi sai sau debounce.
- Chi phí AWS theo hóa đơn thực tế và giả định traffic; tách phần AWS với phần cứng.

## 5. Bàn giao giữa 4 người

1. Người Pi cung cấp fixture `vehicle_detected` hợp lệ/sai và ghi chú confidence.
2. Người ESP gate cung cấp log `gate_telemetry` và `display_telemetry` cho cả hai cần.
3. Người ESP slots cung cấp 18 ID và snapshot đầy đủ sau boot/reconnect.
4. Người backend/web cung cấp tài khoản demo admin/kiosk, API contract, bảng giá và trạng thái email SES.
5. Cả nhóm chạy SIM-01 → SIM-16 và quay video ít nhất một luồng vào/ra liên tục.
