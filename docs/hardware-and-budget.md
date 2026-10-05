# Phần cứng, đấu nối và dự toán

Giá tham khảo tại Việt Nam, kiểm tra **05/10/2026**. Giá bán thay đổi theo cấu hình, VAT, vận chuyển và cửa hàng. Dòng có “ước tính” là ngân sách để lập kế hoạch, **chưa phải báo giá xác nhận**. Sơ đồ mặt bãi nằm ở [parking-layout.md](parking-layout.md).

## 1. Danh mục phần cứng MVP

| Vật tư | Số lượng | Giá đơn vị tham khảo | Thành tiền tham khảo | Vai trò/nguồn |
|---|---:|---:|---:|---|
| Raspberry Pi 5 (ưu tiên 4 GB RAM) | 1 | từ 3.300.000 ₫ | 3.300.000–4.200.000 ₫ | OCR và camera; [giá từ nhà bán](https://raspberrypi.vn/san-pham/mach-may-tinh-raspberry-pi-5?attribute_pa_ram=4gb), giá chính xác theo biến thể cần chốt khi mua |
| Camera Module 3 12 MP, bản thường hoặc góc rộng tùy góc lắp | 1 | từ 890.000 ₫ | 890.000–1.200.000 ₫ | Hai vùng làn; [giá từ nhà bán](https://raspberrypi.vn/san-pham/raspberry-pi-camera-module-v3-12mp-ong-kinh-lay-net-tu-dong) |
| ESP32 DevKit V1 30 pin | 2 | 120.000 ₫ | 240.000 ₫ | Một board cổng, một board ô; [giá tham khảo](https://pyworld.vn/san-pham/esp32-devkit-v1-30pin.html) |
| Cảm biến ToF VL53L0X | 1 | 115.000 ₫ | 115.000 ₫ | Ô F1-A1; [giá tham khảo](https://hshop.vn/cam-bien-khoang-cach-tof-laser-radar-vl53l0x) |
| MCP23017 16 GPIO I²C | 2 | 40.000–75.000 ₫ ước tính | 80.000–150.000 ₫ | Đọc 17 nút; [ví dụ module](https://linhkienx.com/mcp23017-e-ss-mach-mo-rong-i2c-16-chan-i-o) |
| Nút nhấn + điện trở/dây cắm | 17 | 3.000–7.000 ₫ ước tính | 51.000–119.000 ₫ | Một nút cho mỗi ô mô phỏng |
| Servo SG90 hoặc MG90S cho cần mô hình | 2 | 35.000–70.000 ₫ ước tính | 70.000–140.000 ₫ | Cần vào/ra; chọn lực kéo theo chiều dài cần |
| OLED I²C 0,96 inch 128×64 | 1 | 80.000–150.000 ₫ ước tính | 80.000–150.000 ₫ | Hiển thị ô, đường ngắn, phí |
| Nguồn USB-C 5 V/5 A phù hợp Pi 5 | 1 | khoảng 330.000 ₫ | 330.000 ₫ | [nguồn tham khảo trên trang Pi 5](https://raspberrypi.vn/san-pham/mach-may-tinh-raspberry-pi-5?attribute_pa_ram=4gb) |
| Nguồn 5 V/2 A riêng cho servo | 1 | 100.000–200.000 ₫ ước tính | 100.000–200.000 ₫ | Tránh sụt áp ESP/Pi |
| Thẻ microSD 32 GB | 1 | 200.000–450.000 ₫ ước tính | 200.000–450.000 ₫ | Hệ điều hành Pi |
| Cáp camera đúng đầu nối Pi 5, giá đỡ camera | 1 bộ | 90.000–180.000 ₫ ước tính | 90.000–180.000 ₫ | Cần kiểm tra cáp 22-pin phía Pi 5 trước khi mua |
| Breadboard/perfboard, dây, jack, vật tư điện | 1 bộ | 150.000–300.000 ₫ ước tính | 150.000–300.000 ₫ | Đấu nối và cố định |
| Mặt bãi 2 tầng, 2 cần chắn, xe mô hình, biển thẻ xanh/đỏ | 1 bộ | 300.000–700.000 ₫ ước tính | 300.000–700.000 ₫ | Dựng sa bàn |
| Đèn chiếu sáng vùng biển số | 1 | 50.000–150.000 ₫ ước tính | 50.000–150.000 ₫ | Giữ OCR ổn định |

**Tổng ngân sách phần cứng:** khoảng **6,0–8,7 triệu ₫**, chưa gồm VAT, vận chuyển và màn hình kiosk. Có thể giảm mạnh nếu nhóm đã có Pi/camera/nguồn. Laptop hoặc tablet hiện có dùng để hiện QR và dashboard; nếu không có màn hình nào ở cổng, cần bổ sung một màn hình đủ lớn để khách quét QR.

## 2. Đấu nối logic

### Pi 5

- Camera qua CSI bằng cáp phù hợp Pi 5; Wi-Fi/Ethernet tới AWS IoT Core.
- Không điều khiển trực tiếp servo. Dùng nguồn Pi riêng, ưu tiên loại 5 V/5 A.
- Một camera nhìn hai vạch dừng; cấu hình ROI `entry` và `exit`. Đặt góc sao cho biển số đủ pixel, có đèn ổn định và hai xe không chồng nhau trong ảnh.

### ESP32 `gate-01`

- PWM servo cổng vào và cổng ra ở **hai GPIO riêng**; firmware gán `entry`/`exit` cố định.
- OLED dùng I²C (SDA/SCL) 3,3 V nếu module cho phép; kiểm tra mức kéo lên của module.
- Servo cấp từ nguồn 5 V/2 A riêng, **mass chung** với ESP32; tín hiệu điều khiển từ GPIO. Không lấy dòng servo từ GPIO/nguồn USB của Pi.
- Nút dừng khẩn/mở tay là phần nên có khi mô hình cơ khí lớn hơn; MVP dùng servo nhỏ và nút ngắt nguồn cơ cấu khi thao tác.

### ESP32 `slots-01`

- Hai MCP23017 cùng bus I²C, địa chỉ khác nhau (ví dụ 0x20 và 0x21); 17 nút active-low với pull-up, số nút map cố định tới 17 `slot_id`.
- Một VL53L0X đặt trên F1-A1, cùng bus I²C ở địa chỉ khác. Hiệu chỉnh khoảng cách có xe/không xe trên sa bàn thực và lấy nhiều mẫu trước khi đổi trạng thái.
- Ưu tiên tất cả logic I²C ở 3,3 V. Nếu mua module kéo lên 5 V, dùng chuyển mức phù hợp trước khi nối ESP32.
- Nút nhấn đảo trạng thái giả lập; lưu NVS. Không dùng nút bấm trên `gate-01` để tránh nhầm lệnh cổng với trạng thái ô.

## 3. Điều kiện “đủ phần cứng”

Hai ESP32, Pi/camera, một cảm biến và 17 nút **đủ cho demo logic** vào/ra/gán ô nếu có nguồn, servo/cần, OLED, Wi-Fi và thiết bị hiện QR. Một OLED 0,96 inch quá nhỏ để trông cậy vào việc quét QR theo phiên; dùng laptop/tablet đã có hoặc màn hình HDMI ở kiosk.

Không có cảm biến xe qua hai cổng nên hệ thống cần quản trị xác nhận xe đã qua trên web. Nếu muốn tự động hoàn toàn sau này, thêm cảm biến tia hồng ngoại tại mỗi làn; không tính vào MVP.

## 4. Chi phí AWS cần dự trù

- Bật AWS Budgets trước khi demo; đặt cảnh báo nhỏ (ví dụ 5 USD và 10 USD) và tắt tài nguyên sau buổi demo.
- IoT Core tính theo kết nối, message và Rules; giảm chi phí bằng cách gửi `slot_changed` khi đổi và `slots_snapshot` mỗi 30 giây, không gửi 18 message riêng liên tục. [Bảng giá IoT Core](https://aws.amazon.com/iot-core/pricing/).
- Lambda, API Gateway, DynamoDB, S3/CloudFront, Cognito và CloudWatch có cách tính phí khác nhau theo vùng/sử dụng. Dùng [AWS Pricing Calculator](https://calculator.aws/) cho region định triển khai; không giả định toàn bộ hệ thống miễn phí.
- SES là kênh thông báo chính; bảng giá AWS có thể đổi theo plan/region. AWS công bố plan Essentials từ 07/2026 ở mức **0,16 USD/1.000 email trong bậc đầu**; 500 email khoảng **0,08 USD tiền gửi cơ bản** trước các ưu đãi/phụ phí. Đây chỉ là phép nhân tham khảo, không phải tổng chi phí AWS. [Thông báo plan SES](https://aws.amazon.com/about-aws/whats-new/2026/07/amazon-ses-pricing-plans/), [giá SES](https://aws.amazon.com/ses/pricing/).
- Tài khoản SES ở sandbox chỉ gửi tới địa chỉ đã xác minh; demo với email nhóm trước, xin production access nếu muốn khách nhập email bất kỳ. [Hướng dẫn SES sandbox](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).

**Dự toán đúng trước khi mua/triển khai:** chốt region AWS, số giờ thiết bị online, số xe/ngày, số email/ngày, số lượt API, mức lưu CloudWatch/S3; lấy báo giá mới và kiểm tra VAT.
