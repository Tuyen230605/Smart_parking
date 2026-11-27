# Hướng dẫn cài đặt

Làm theo thứ tự từ trên xuống. Các lệnh chạy trên laptop, trừ khi ghi là chạy trên Pi.

## 0. Cần chuẩn bị

| Thứ cần có | Ghi chú |
|---|---|
| Laptop Linux hoặc macOS (Windows thì dùng WSL) | Chạy script triển khai và nạp ESP32 |
| Tài khoản AWS | Gói miễn phí dùng được |
| Node.js 20 trở lên, Python 3.11 trở lên | Kiểm tra bằng `node -v`, `python3 -V` |
| PlatformIO | `pip install platformio`, dùng để nạp ESP32 |
| Raspberry Pi 5 + camera, ESP32-S3 + servo SG90, ESP32 + 18 nút | Xem [hardware-and-budget.md](hardware-and-budget.md) |

## 1. Cài AWS CLI và đăng nhập

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip && sudo ./aws/install && aws --version
```

Không dùng khóa của tài khoản root. Tạo một tài khoản IAM riêng:

1. AWS Console, vào IAM, chọn Users, Create user, đặt tên `smart-parking-deployer`.
2. Gắn quyền `AdministratorAccess` (chỉ dùng cho đồ án, xóa sau khi xong).
3. Trong tài khoản vừa tạo, vào Security credentials, tạo Access key loại Command Line Interface.
4. Trên laptop:
   ```bash
   aws configure
   # Access Key ID, Secret: dán từ bước 3
   # Default region name: ap-southeast-1
   # Default output format: json
   aws sts get-caller-identity   # in ra mã tài khoản là được
   ```

## 2. Dựng hạ tầng AWS

```bash
cd infra/aws
./deploy.sh
```

Lần đầu script hỏi hai email: email gửi hướng dẫn cho khách và email nhận cảnh báo chi phí. Sau đó script tự làm hết: tạo kho chứa mã Lambda, dựng stack `smart-parking-dev`, tạo 18 ô và bảng giá, ghi cấu hình cho web. Lần đầu mất khoảng 5–10 phút vì phải chờ CloudFront. Chạy lại lúc nào cũng được, CloudFormation chỉ sửa phần thay đổi.

Các giá trị riêng (email, khóa ký mã QR) được lưu ở `secrets/deploy.env`. Thư mục `secrets/` không được commit.

Ngay sau đó:

1. Mở hộp thư của email gửi, bấm link xác minh của Amazon SES. Chưa bấm thì không gửi được email.
2. Tài khoản SES mới đang ở chế độ thử (sandbox), chỉ gửi được tới email đã xác minh. Để demo, xác minh thêm email của các thành viên:
   ```bash
   aws sesv2 create-email-identity --email-identity ten@gmail.com
   ```
3. Tạo tài khoản đăng nhập web (script hỏi mật khẩu, ít nhất 8 ký tự và có số):
   ```bash
   ./create-users.sh   # tạo admin (nhóm ADMIN) và kiosk (nhóm KIOSK)
   ```

Nếu bước dựng hạ tầng lỗi ở CloudFront (tài khoản mới chưa được dùng CloudFront), chạy `ENABLE_CDN=false WEB_BASE_URL_OVERRIDE=http://<ip-laptop>:5173 ./deploy.sh` rồi chạy web trên laptop như mục 4.

## 3. Cấp chứng chỉ cho thiết bị

```bash
WIFI_SSID="TenWifi" WIFI_PASS="matkhau" ./provision-devices.sh
```

Script tạo 3 thiết bị trên IoT Core: `pi-01`, `gate-01`, `slots-01`. Mỗi thiết bị có chứng chỉ riêng và chỉ được dùng đúng kênh tin nhắn của mình. Script sinh ra:

| Tệp | Dùng cho |
|---|---|
| `secrets/certs/<thiết bị>/cert.pem`, `private.key` | Chương trình giả lập trên laptop |
| `edge/raspberry-pi-vision/config.local.toml` | Pi |
| `firmware/esp32-*/include/secrets.h` | Hai ESP32 |

Nhớ truyền `WIFI_SSID` và `WIFI_PASS`. Nếu không, Wi-Fi trong `secrets.h` sẽ bị thay bằng chữ mẫu. Chạy lại script vẫn an toàn: chứng chỉ cũ được giữ nguyên.

## 4. Đưa web lên

```bash
./deploy-web.sh   # build, đưa lên S3, làm mới CloudFront, in ra địa chỉ web
```

Muốn chạy web trên laptop để sửa giao diện: `cd web && npm install && npm run dev` (mở `http://localhost:5173`, gọi API thật).

| Trang | Dùng cho | Đăng nhập |
|---|---|---|
| `/` | Sơ đồ 18 ô | Không |
| `/kiosk` | Màn hình ở cổng, hiện mã QR lớn | `kiosk` |
| `/admin` | Quản trị: danh sách xe, cho vào, cho ra, thu tiền, thiết bị, bảng giá | `admin` |
| `/s/<mã>` | Điện thoại của khách sau khi quét QR | Không |

## 5. Raspberry Pi

### 5.1 Cho Pi lên mạng

Pi cần Internet để kết nối AWS. Có hai cách:

- Cắm dây LAN từ router vào Pi.
- Không có router (ví dụ ở trường): cắm dây LAN thẳng từ laptop sang Pi, rồi cho laptop chia sẻ Internet qua cổng LAN. Với laptop Ubuntu, profile mạng dây tên `Profile 1`:
  ```bash
  nmcli connection modify "Profile 1" ipv4.method shared ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
  nmcli connection up "Profile 1"
  ip neigh show dev enp3s0   # xem IP của Pi, thường là 10.42.0.x
  ```
  Laptop sẽ có địa chỉ `10.42.0.1` và cấp IP cho Pi. Muốn trả cổng LAN về IP tĩnh cũ:
  `nmcli connection modify "Profile 1" ipv4.method manual ipv4.addresses 192.168.0.100/24`.

Kiểm tra trên Pi: `curl -sS -o /dev/null https://aws.amazon.com && echo co-internet`. Không dùng `ping amazon.com` vì amazon.com chặn ping.

### 5.2 Cài chương trình

Một lệnh trên laptop là xong:

```bash
cd infra/aws && ./setup-pi.sh oi@<ip-pi>
```

Script kiểm tra Internet của Pi, tải mã nguồn về `~/Cloud-Course`, chép chứng chỉ, cài thư viện và bật dịch vụ `pi-vision`. Dịch vụ tự chạy mỗi khi bật Pi. Kiểm tra:

```bash
ssh oi@<ip-pi> 'journalctl -u pi-vision -n 20'   # phải thấy "Đã kết nối MQTT"
```

### 5.3 Chỉnh camera

Mở trang camera `http://<ip-pi>:8000` trên laptop. Nửa trái khung hình là làn vào, nửa phải là làn ra. Đưa tay vào một làn thì khung làn đổi màu và hệ thống tạo một lượt xe. Cách chỉnh vùng làn và độ nhạy xem ở [README của Pi](../edge/raspberry-pi-vision/README.md).

## 6. Hai bo mạch ESP32

ESP32 chỉ dùng được Wi-Fi 2,4 GHz. Wi-Fi đã được ghi vào `include/secrets.h` ở mục 3; muốn đổi thì sửa hai dòng `WIFI_SSID`, `WIFI_PASS` trong tệp đó rồi nạp lại.

Cắm mỗi bo mạch vào laptop, nạp lần lượt từng bo:

```bash
cd firmware/esp32-gates && pio run -t upload           # ESP32-S3, cần chắn
cd firmware/esp32-slot-sensors && pio run -t upload    # ESP32, 18 nút
```

Xem log bằng `pio device monitor`. Phải có dòng `✓ đã kết nối AWS IoT` và không lặp lại dòng "kết nối…" mỗi 2 giây.

Cách nối dây:

- ESP32-S3: dây tín hiệu servo vào GPIO18. Servo cần nguồn 5 V riêng (chân `5Vin` của nhiều bo ESP32-S3 không có điện khi cắm USB) và phải nối chung GND với ESP32-S3. Mỗi lần khởi động, servo tự quay thử qua lại để kiểm tra dây và nguồn.
- ESP32: mỗi nút một chân vào GPIO, chân kia vào GND. Bảng chân ở [parking-layout.md](parking-layout.md).

Không nên cắm cả hai bo vào cùng một laptop khi chạy lâu: cổng USB có thể không đủ điện, bo mạch sẽ tự khởi động lại. Sau khi nạp, cắm mỗi bo vào một cục sạc riêng là chạy được.

## 7. Chạy thử khi chưa có thiết bị

Có thể giả lập hai ESP32 và camera ngay trên laptop:

```bash
python3 -m venv .venv && .venv/bin/pip install -r simulation/requirements.txt
.venv/bin/python simulation/mock_gate.py    # thay ESP32-S3
.venv/bin/python simulation/mock_slots.py   # thay ESP32 18 nút, gõ F1-A1 để đảo một ô
.venv/bin/python simulation/fake_car.py vao 51A-12345   # giả một xe ở làn vào
```

Chương trình giả lập dùng đúng chứng chỉ và định dạng tin nhắn như thiết bị thật. Không chạy giả lập và thiết bị thật cùng lúc: AWS chỉ cho mỗi tên thiết bị một kết nối, hai bên sẽ đá nhau ra liên tục. Mạng chặn cổng 8883 thì thêm `IOT_PORT=443` trước lệnh.

## 8. Kịch bản demo

Trước khi bắt đầu, mở `/admin`, thẻ Tổng quan: `pi-01`, `gate-01`, `slots-01` phải ONLINE.

1. Màn hình A mở `/kiosk`. Màn hình B mở `/admin/sessions`.
2. Đưa tay vào nửa trái khung camera (hoặc bấm *Thử xe VÀO* trên trang camera). Trang Phiên đỗ hiện "Chờ cho vào – 11111".
3. Bấm *Cho vào*. Servo quay trái rồi về giữa sau 5 giây. Xe vào danh sách trong bãi. Kiosk hiện mã QR.
4. Quét QR bằng điện thoại, chạm chọn một ô trống (thử một ô tầng 2 để thấy đường lên dốc). Nhập email đã xác minh, có thể tích "Ghi nhớ email cho biển số". Kiểm tra hộp thư.
5. Bấm nút của ô vừa đỗ trên sa bàn. Sơ đồ `/` đổi ô đó sang "Có xe".
6. Đưa tay vào nửa phải khung camera (hoặc bấm *Thử xe RA*). Trang Phiên đỗ hiện "Chờ cho ra" và số tiền. Dưới 15 phút thì bấm *Cho ra*; nếu có phí thì bấm *Đã thu … cho ra*. Servo quay phải, xe rời danh sách.

Muốn thấy tiền ngay mà không phải chờ 15 phút: vào Bảng giá, đặt thời gian miễn phí bằng 0, demo xong thì đặt lại 15.

## 9. Sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Thiết bị không kết nối AWS | Kiểm tra Wi-Fi, giờ trên máy, thử `IOT_PORT=443` |
| ESP32 kết nối xong lại bị ngắt mỗi 2 giây | Firmware cũ, nạp lại bản mới |
| ESP32 không vào được Wi-Fi điện thoại | Điểm phát đang ở 5 GHz, đổi sang 2,4 GHz |
| Log ESP32-S3 có `[servo] → 180°` mà servo không quay | Servo thiếu nguồn 5 V, xem mục 6 |
| Bo ESP32 khởi động lại liên tục, log báo "Brownout" | Thiếu điện, cắm bo vào nguồn riêng |
| Trang camera không có hình, log Pi báo "Camera frontend has timed out" | Tắt Pi, cắm lại cáp camera cho chặt |
| Pi tự tắt sau vài phút | Cáp camera lỏng hoặc nguồn yếu; dùng nguồn 5 V/5 A |
| Có xe ở làn mà cần không mở | Phải bấm *Cho vào* trên trang Phiên đỗ; xem cảnh báo ở Tổng quan |
| Sơ đồ toàn ô xám (không rõ) | Bo mạch 18 nút chưa kết nối |
| Email báo `FAILED` | Email gửi hoặc email nhận chưa được xác minh trong SES |
| Web báo chưa đăng nhập | Đăng xuất rồi đăng nhập lại |

Xem log Lambda: `aws logs tail /aws/lambda/smart-parking-dev-iot --follow` (tương tự với `-api`, `-jobs`). Xem tin nhắn MQTT trực tiếp: AWS Console, IoT Core, MQTT test client, đăng ký kênh `parking/v1/site-01/#`.

## 10. Chi phí và gỡ bỏ

Các dịch vụ đều tính theo mức dùng. Chạy demo vài giờ mỗi ngày tốn chưa tới 1 USD mỗi tháng. AWS Budgets gửi email khi chi phí tháng vượt 5 USD. Gỡ toàn bộ sau khi xong đồ án:

```bash
cd infra/aws && ./destroy.sh
```
