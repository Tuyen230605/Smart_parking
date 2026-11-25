# Mô phỏng và nghiệm thu đầu cuối

Mục tiêu là dựng đủ hành vi của **18 ô bằng 18 nút bấm**, hai làn qua một camera (phát hiện tay/xe mô hình) và một servo cần chắn 3 vị trí qua một ESP32-S3. Kịch bản liên kết với [use case](use-cases.md); payload lấy từ [MQTT contract](mqtt-contract.md) và [API contract](api-contract.md).

## 1. Các chế độ chạy

| Chế độ | Thiết bị | Mục đích |
|---|---|---|
| Mock local | Script thay Pi/gate/slots, broker MQTT local | Phát triển backend/web không cần sa bàn/AWS |
| AWS dev | Mock device hoặc một số thiết bị thật → IoT Core | Chốt certificate, topic, IoT Rule và Lambda |
| Sa bàn đầy đủ | Pi/camera, ESP gate/servo/OLED, ESP slots/18 nút | Nghiệm thu hành vi phần cứng, email và web |

Mock phải phát **cùng schema v1** và **cùng device_id** như thiết bị thật; không làm API riêng cho demo. Có thể dùng biển số giả trong fixture để không cần dữ liệu thật.

## 2. Bố trí đầu vào

- Camera nhìn hai khung làn: nửa trái = `ENTRY`, nửa phải = `EXIT` (chỉnh `lanes.*.roi`). Đưa tay/xe mô hình vào khung = một lượt.
- 18 nút nối thẳng GPIO theo bảng ở [parking-layout.md](parking-layout.md). Một nhấn đảo trạng thái ô.
- Kiosk là laptop/tablet hiện QR động + bản đồ; OLED hiện chỉ dẫn/phí ngắn. Màn hình admin trên cùng web app, tài khoản `ADMIN`.

## 3. Kịch bản nghiệm thu

| ID | Thiết lập và thao tác | Điều kiện đạt |
|---|---|---|
| SIM-01 | Tay vào làn vào, bãi trống | Một phiên **Chờ cho vào** biển `11111`; cần chưa mở; OLED `XE 11111` |
| SIM-02 | Quản trị bấm Cho vào | Servo quay trái rồi về giữa; xe vào danh sách (web + trang camera); kiosk có QR + bản đồ |
| SIM-03 | Quét QR, chọn ô tầng 2, nhập email | Đường đi vẽ tới ram rồi tới ô; SES nhận một email ghi đúng ô đã chọn; gửi lặp bị chặn |
| SIM-04 | Tích "Ghi nhớ email", cho xe ra rồi vào lại | Lần vào sau email tự gửi; hủy liên kết bằng link → lần sau không gửi |
| SIM-05 | Bấm một nút ô rồi bấm lại | Ô lần lượt có xe/trống; sau reset ESP vẫn đúng trạng thái đã lưu NVS; phiên không đổi |
| SIM-06 | Bấm đủ 18 nút rồi Cho vào | Báo bãi đầy, không mở cần vào |
| SIM-07 | Tay vào làn ra khi có 2 xe | Chọn xe số lớn nhất, hiện phí; cần chỉ mở khi bấm Cho ra (có phí thì sau khi ghi thu tiền); xe rời danh sách |
| SIM-08 | Giữ tay lâu trong khung / rút ra đưa lại | Chỉ một lượt mỗi lần đưa tay |
| SIM-09 | Hai lượt chờ vào cùng lúc | Biển khác nhau (`11111`, `22222`); từ chối một lượt thì số đó được dùng lại |
| SIM-10 | Replay cùng `event_id`/`command_id` | Không thêm phiên, gửi email hoặc chạy servo lần hai |
| SIM-11 | Ngắt ESP slots > 90 giây | Các ô `UNKNOWN`; xe vẫn được cho vào, không có ô gợi ý |
| SIM-12 | Ngắt Wi-Fi ESP gate, phát lệnh cũ rồi nối lại | Lệnh đã quá hạn bị bỏ; servo không mở |
| SIM-13 | Tay vào làn ra khi bãi trống | Bỏ qua, không tạo phiên |
| SIM-14 | SES lỗi hoặc sandbox chặn email | Web vẫn chỉ đường; admin thấy `FAILED`; xe vẫn vào |
| SIM-15 | Token QR hết 15 phút hoặc dùng lại để gửi email | Trả `410 TOKEN_EXPIRED` hoặc `409 EMAIL_ALREADY_SENT` |
| SIM-16 | Dữ liệu định danh đã đến hạn 10 ngày | API không trả biển số/email/token, job purge dọn dữ liệu |

## 4. Số liệu nên báo cáo

- Tỷ lệ phát hiện đúng lượt (đưa tay → đúng một sự kiện) và báo nhầm khi không có gì, ở điều kiện đủ sáng/thiếu sáng. Ghi số mẫu và cách tính.
- Độ trễ từ Pi event đến lúc trang Phiên đỗ hiện lượt; từ lúc bấm Cho vào/Cho ra đến servo quay (ESP ACK); đo trung vị và lớn nhất.
- Số lần nút bounce gây đổi sai sau debounce.
- Chi phí AWS theo hóa đơn thực tế và giả định traffic; tách phần AWS với phần cứng.

## 5. Bàn giao giữa 4 người

1. Người Pi cung cấp ROI/ngưỡng `[presence]` đã hiệu chỉnh và log sự kiện.
2. Người ESP gate cung cấp log `gate_telemetry` và `display_telemetry` cho cả hai cần.
3. Người ESP slots cung cấp 18 ID và snapshot đầy đủ sau boot/reconnect.
4. Người backend/web cung cấp tài khoản demo admin/kiosk, API contract, bảng giá và trạng thái email SES.
5. Cả nhóm chạy SIM-01 → SIM-16 và quay video ít nhất một luồng vào/ra liên tục.
