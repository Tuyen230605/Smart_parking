# Kiểm thử

## Các mức kiểm thử

| Mức | Kiểm tra gì | Cách chạy |
|---|---|---|
| Nghiệp vụ | Toàn bộ xử lý trên Lambda, chạy với DynamoDB giả lập nên không tốn tiền AWS | `cd backend && ../.venv/bin/python -m pytest -q tests` |
| Phát hiện xe | Phần so ảnh nền trên Pi | `cd edge/raspberry-pi-vision && python -m unittest test_presence` |
| Tích hợp | Thiết bị giả lập hoặc thật kết nối AWS thật | Chương trình trong `simulation/` hoặc thiết bị thật |
| Thiết bị thật | Pi, ESP32-S3, ESP32 chạy cùng AWS | Theo kịch bản demo trong [setup-guide.md](setup-guide.md) |

Kết quả hiện tại: 16/16 kiểm thử nghiệp vụ và 5/5 kiểm thử phát hiện xe đạt.

## Chạy thử khi chưa có thiết bị

Chương trình giả lập dùng đúng chứng chỉ và định dạng tin nhắn như thiết bị thật, nên đám mây không phân biệt được:

| Chương trình | Thay cho | Cách dùng |
|---|---|---|
| `simulation/mock_gate.py` | ESP32-S3 | In ra trạng thái cần khi có lệnh |
| `simulation/mock_slots.py` | ESP32 18 nút | Gõ `F1-A1` hoặc số 0–17 để đảo một ô; `full`, `clear` để đổi tất cả |
| `simulation/fake_car.py` | Camera của Pi | `fake_car.py vao 51A-12345` hoặc `fake_car.py ra 51A-12345` |

Khi đã có Pi thì dùng nút *Thử xe VÀO*, *Thử xe RA* trên trang camera.

## Kịch bản nghiệm thu

| Mã | Làm gì | Kết quả đúng |
|---|---|---|
| SIM-01 | Đưa tay vào làn vào | Một phiên "Chờ cho vào" với biển 11111, cần chưa mở |
| SIM-02 | Bấm *Cho vào* | Servo quay trái rồi về giữa; xe vào danh sách trên web và trên Pi; kiosk có QR |
| SIM-03 | Quét QR, chọn ô tầng 2, nhập email | Đường đi vẽ lên dốc; nhận đúng một email ghi ô đã chọn |
| SIM-04 | Tích ghi nhớ email, cho xe ra rồi vào lại | Lần vào sau tự nhận email; hủy liên kết thì không gửi nữa |
| SIM-05 | Bấm một nút ô, bấm lại, khởi động lại ESP32 | Ô đổi trạng thái; sau khi khởi động lại vẫn đúng; phiên đỗ không đổi |
| SIM-06 | Bấm đủ 18 nút rồi bấm *Cho vào* | Báo bãi đầy, cần không mở |
| SIM-07 | Đưa tay vào làn ra khi có 2 xe | Chọn xe số lớn nhất, hiện số tiền; chỉ mở cần khi bấm *Cho ra*; xe rời danh sách |
| SIM-08 | Giữ tay lâu trong khung, rút ra rồi đưa lại | Mỗi lần đưa tay chỉ một lượt |
| SIM-09 | Hai lượt chờ vào cùng lúc, từ chối một lượt | Hai biển khác nhau; số bị từ chối được dùng lại |
| SIM-10 | Gửi lặp cùng một tin nhắn hoặc lệnh | Không tạo thêm phiên, không mở cần lần hai |
| SIM-11 | Rút điện ESP32 18 nút hơn 90 giây | Ô thành "không rõ"; xe vẫn được cho vào |
| SIM-12 | Gửi lệnh cũ sau khi ESP32-S3 kết nối lại | Lệnh quá hạn bị bỏ, servo không quay |
| SIM-13 | Đưa tay vào làn ra khi bãi trống | Bỏ qua, không tạo phiên |
| SIM-14 | Gửi email khi SES lỗi | Vẫn xem được đường đi; trang quản trị ghi gửi thất bại |
| SIM-15 | Dùng link QR hết hạn hoặc gửi email lần hai | Báo link hết hạn hoặc đã gửi |
| SIM-16 | Dữ liệu quá 10 ngày | Tác vụ dọn dữ liệu xóa biển số, email |

Cả 16 kịch bản đều đạt.

## Số liệu đã đo

- Thời gian từ lúc gửi sự kiện có xe tới khi AWS xử lý xong (10 lần đo): trung vị 0,22 giây, lâu nhất 1,99 giây (lần đầu, khi Lambda vừa khởi động).
- Chi phí AWS từ 1/11 đến 27/11/2026: khoảng 0,09 USD.
