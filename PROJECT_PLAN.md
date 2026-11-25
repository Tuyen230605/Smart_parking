# Kế hoạch triển khai Smart Parking

Thiết kế chi tiết: [kiến trúc](docs/architecture.md) · [use case](docs/use-cases.md) · [bãi xe](docs/parking-layout.md) · [phần cứng/chi phí](docs/hardware-and-budget.md).

## 1. Mục tiêu nghiệm thu

Demo một lượt xe vào (quản trị bấm Cho vào), nhận ô gợi ý/đường đi qua OLED và QR, tùy chọn nhập email (và ghi nhớ theo biển số); một lượt xe ra, tính phí mô phỏng, quản trị thu tiền và bấm Cho ra. Dashboard cho quản trị theo dõi 18 ô/3 thiết bị/phiên đỗ, công khai cho khách trạng thái ô và đường đến ô của phiên. Có kịch bản lượt lặp, bãi đầy, mất kết nối, lệnh trùng và dọn dữ liệu định danh sau 10 ngày.

## 2. Phạm vi đã chốt

| Mục | Quyết định |
|---|---|
| Bãi xe | 2 tầng, mỗi tầng 3 hàng × 3 ô = 18 ô |
| Camera | Một camera nối Pi 5 nhìn hai vùng làn; có vật (tay/xe mô hình) trong vùng = có xe; biển số demo do backend đánh |
| Cổng | Một ESP32-S3 điều khiển một servo cần chắn 3 vị trí (trái = vào, phải = ra) và một OLED |
| Ô | Một ESP32 đọc 18 nút giả lập nối thẳng GPIO; ô chỉ để chỉ chỗ trống, không gán cho xe |
| Thông báo | Email SES theo từng lượt nếu khách nhập email ở QR; không dùng SMS trong MVP |
| Guest | Không cần tài khoản; xem sơ đồ và QR phiên |
| Admin | Đăng nhập, xem phiên/thiết bị, xử lý lỗi, thu phí demo |
| Tính phí | Bảng giá cấu hình, không tích hợp thanh toán thật |
| Dữ liệu định danh | Tối đa 10 ngày từ thời điểm thu thập; không tự dùng email cũ cho lượt sau |

## 3. Phân công 4 người

Checklist chi tiết, quy tắc Git và thứ tự làm: [docs/team-tasks.md](docs/team-tasks.md).

| Người | Thiết bị | Trang trong web app chung | Việc và sản phẩm bàn giao |
|---|---|---|---|
| 1 — Pi/vision + khách | Pi 5 + camera | `/s/:token` (`web/src/pages/guest/`) | Hai ROI, phát hiện vật trong làn, dedupe; publish `vehicle_detected`; trang camera hiện danh sách xe; trang QR/email của khách; fixture và báo cáo độ chính xác |
| 2 — ESP cổng + kiosk | `gate-01`: 2 servo + OLED | `/kiosk` (`web/src/pages/kiosk/`) | Firmware lệnh đúng cần/ACK/OLED, mock gate; kiosk QR lớn và component điều khiển cổng cho admin |
| 3 — ESP ô + sơ đồ | `slots-01`: 18 nút | `/` (`web/src/pages/public/`, `FloorMap`) | Sa bàn, 18 nút GPIO, debounce/NVS, snapshot; mock slots; sơ đồ 18 ô công khai |
| 4 — AWS/backend + quản trị | — | `/admin` (`web/src/pages/admin/`, `auth.ts`) | IoT Core, Lambda/API, DynamoDB, SES, Cognito, cho vào/cho ra, biển demo, phí, token QR, email ghi nhớ theo biển; cert thiết bị; trang quản trị; deploy web |

**Tích hợp chung:** thiết bị nói chuyện với AWS qua [MQTT v1](docs/mqtt-contract.md); web nói chuyện với backend qua [API v1](docs/api-contract.md). Web là **một app duy nhất** ([web/](web/README.md), Vite + React + TypeScript): dùng chung lớp `src/api` (có API giả để làm trước khi backend xong), chung layout và CSS, mỗi người sở hữu một thư mục trang.

## 4. Mốc 6 tuần

| Mốc | Đầu ra kiểm tra được |
|---|---|
| Tuần 1 — Thiết kế | Chốt sơ đồ cơ khí, linh kiện, pinout, topic/API v1, giá demo và region AWS |
| Tuần 2 — Mô phỏng | Mock Pi/ESP32, backend local, web sơ đồ/QR, UC-01 đến UC-04 chạy bằng message giả |
| Tuần 3 — Phần cứng | Pi phát hiện xe trong làn; servo 3 vị trí + OLED; 18 nút báo đúng ô |
| Tuần 4 — Cloud | IoT Core/Rules, Lambda/API, DynamoDB, Cognito admin, SES sandbox với email nhóm |
| Tuần 5 — Tích hợp | Lượt vào/ra/tính phí/email đầu cuối; kịch bản lượt lặp, full, offline, replay |
| Tuần 6 — Hoàn thiện | Tối ưu góc camera, báo cáo số liệu, chi phí, video demo, tài liệu vận hành và dọn dữ liệu |

## 5. Tiêu chí hoàn thành

- 18 ô đúng ID/trạng thái, lấy từ 18 nút.
- Hai cần nhận lệnh riêng, không mở nhầm, không thi hành lệnh cũ/trùng.
- QR theo từng phiên; email tùy chọn của lượt này; lượt sau không tự gửi email cũ.
- Web guest/kiosk/admin cùng đọc một nguồn dữ liệu; admin có xác thực.
- Fee preview và final được tính theo bảng giá; mở cổng ra chỉ sau thao tác quản trị phù hợp.
- Dữ liệu định danh hết hạn không còn truy cập qua API; không để khóa/secret trong repo.

## 6. Rủi ro cần kiểm tra sớm

1. Một camera có thể không đọc rõ hai làn cùng lúc. Thử góc/ánh sáng/độ phân giải trong tuần 1; nếu không đạt, demo tuần tự từng làn theo cùng thiết kế.
2. OLED nhỏ không đủ để quét QR tin cậy; cần laptop/tablet có sẵn ở kiosk.
3. Chưa có cảm biến xe qua cổng và camera không đọc biển: quản trị bấm Cho vào/Cho ra; biển số là số demo.
4. SES sandbox chỉ gửi tới địa chỉ đã xác minh; cần chuẩn bị email nhóm hoặc xin production access trước demo khách thật.
5. Giá linh kiện/AWS biến động; kiểm tra báo giá và AWS Calculator trước khi mua/bật dịch vụ.
