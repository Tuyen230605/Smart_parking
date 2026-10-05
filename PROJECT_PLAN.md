# Kế hoạch triển khai Smart Parking

Thiết kế chi tiết: [kiến trúc](docs/architecture.md) · [use case](docs/use-cases.md) · [bãi xe](docs/parking-layout.md) · [phần cứng/chi phí](docs/hardware-and-budget.md).

## 1. Mục tiêu nghiệm thu

Demo một lượt xe vào, nhận ô/đường qua OLED và QR, tùy chọn nhập email nhận chỉ dẫn; một lượt xe ra, tính phí mô phỏng và xác nhận thu tiền. Dashboard cho quản trị theo dõi 18 ô/3 thiết bị/phiên đỗ, công khai cho khách trạng thái ô và đường đến ô của phiên. Có kịch bản lỗi OCR, bãi đầy, mất kết nối, lệnh trùng và dọn dữ liệu định danh sau 10 ngày.

## 2. Phạm vi đã chốt

| Mục | Quyết định |
|---|---|
| Bãi xe | 2 tầng, mỗi tầng 3 hàng × 3 ô = 18 ô |
| Camera | Một camera nối Pi 5 nhìn hai vùng làn; thẻ xanh ở làn vào, đỏ ở làn ra |
| Cổng | Một ESP32 điều khiển hai cần chắn và một OLED |
| Ô | Một ESP32 đọc một cảm biến thật ở F1-A1 và 17 nút giả lập |
| Thông báo | Email SES theo từng lượt nếu khách nhập email ở QR; không dùng SMS trong MVP |
| Guest | Không cần tài khoản; xem sơ đồ và QR phiên |
| Admin | Đăng nhập, xem phiên/thiết bị, xử lý lỗi, thu phí demo |
| Tính phí | Bảng giá cấu hình, không tích hợp thanh toán thật |
| Dữ liệu định danh | Tối đa 10 ngày từ thời điểm thu thập; không tự dùng email cũ cho lượt sau |

## 3. Phân công 4 người

| Người | Chủ trì | Việc và sản phẩm bàn giao |
|---|---|---|
| 1 — Pi/vision + giao diện khách | Camera và AI tại biên | Lắp camera nhìn hai ROI, nhận màu thẻ, OCR biển số, confidence/dedupe; publish `vehicle_detected`; trang QR/form email của khách và video fixture |
| 2 — ESP cổng + giao diện cổng | Hai cần chắn + OLED | Đấu nguồn/servo, firmware `gate-01`, lệnh đúng cần/ACK, chỉ ô/phí trên OLED; trang kiosk QR và thao tác cổng trên web |
| 3 — ESP ô + sơ đồ bãi | Một cảm biến + 17 nút | Sa bàn 2 tầng, I²C expander, map 18 ô, debounce/NVS, snapshot MQTT; sơ đồ 18 ô trên web, mock thiết bị và kịch bản |
| 4 — AWS/backend + quản trị | Nghiệp vụ và hạ tầng | IoT Core, Lambda/API, DynamoDB, SES, Cognito, gán ô/tính phí/token QR, trang quản trị và hướng dẫn deploy |

**Tích hợp chung:** người 1 và 4 chốt `vision event` cùng API trang khách; người 2 và 4 chốt gate/display commands cùng API kiosk; người 3 và 4 chốt slot state cùng API sơ đồ. Cả nhóm làm demo đầu cuối, kiểm thử và sửa hợp đồng khi cần. Giao diện là một web app chung; mỗi người chịu trách nhiệm phần mình và dùng cùng API v1.

## 4. Mốc 6 tuần

| Mốc | Đầu ra kiểm tra được |
|---|---|
| Tuần 1 — Thiết kế | Chốt sơ đồ cơ khí, linh kiện, pinout, topic/API v1, giá demo và region AWS |
| Tuần 2 — Mô phỏng | Mock Pi/ESP32, backend local, web sơ đồ/QR, UC-01 đến UC-04 chạy bằng message giả |
| Tuần 3 — Phần cứng | Pi nhận thẻ/biển số; hai servo + OLED; ToF và 17 nút báo đúng ô |
| Tuần 4 — Cloud | IoT Core/Rules, Lambda/API, DynamoDB, Cognito admin, SES sandbox với email nhóm |
| Tuần 5 — Tích hợp | Lượt vào/ra/tính phí/email đầu cuối; kịch bản OCR kém, full, offline, replay |
| Tuần 6 — Hoàn thiện | Tối ưu góc camera, báo cáo số liệu, chi phí, video demo, tài liệu vận hành và dọn dữ liệu |

## 5. Tiêu chí hoàn thành

- 18 ô đúng ID/trạng thái; F1-A1 nhận từ cảm biến thật, 17 ô khác từ nút.
- Hai cần nhận lệnh riêng, không mở nhầm, không thi hành lệnh cũ/trùng.
- QR theo từng phiên; email tùy chọn của lượt này; lượt sau không tự gửi email cũ.
- Web guest/kiosk/admin cùng đọc một nguồn dữ liệu; admin có xác thực.
- Fee preview và final được tính theo bảng giá; mở cổng ra chỉ sau thao tác quản trị phù hợp.
- Dữ liệu định danh hết hạn không còn truy cập qua API; không để khóa/secret trong repo.

## 6. Rủi ro cần kiểm tra sớm

1. Một camera có thể không đọc rõ hai làn cùng lúc. Thử góc/ánh sáng/độ phân giải trong tuần 1; nếu không đạt, demo tuần tự từng làn theo cùng thiết kế.
2. OLED nhỏ không đủ để quét QR tin cậy; cần laptop/tablet có sẵn ở kiosk.
3. Chưa có cảm biến xe qua cổng; quản trị phải xác nhận xe ra.
4. SES sandbox chỉ gửi tới địa chỉ đã xác minh; cần chuẩn bị email nhóm hoặc xin production access trước demo khách thật.
5. Giá linh kiện/AWS biến động; kiểm tra báo giá và AWS Calculator trước khi mua/bật dịch vụ.
