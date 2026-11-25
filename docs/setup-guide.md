# Hướng dẫn dựng hệ thống lên AWS từ đầu đến cuối

Làm theo thứ tự. **Ngày 1**: AWS + web + Pi thật + 2 ESP32 chạy bằng script mock trên laptop. **Ngày 2**: nạp firmware vào 2 ESP32 thật và tắt mock.

```text
                ┌──────────── AWS (ap-southeast-1) ─────────────┐
 Pi 5 + camera ─┤ IoT Core ─ Rule ─ Lambda iot ─ DynamoDB (7 bảng)│
 mock/ESP gate ─┤    ▲                  │                       │
 mock/ESP slots ┤    └── lệnh cần/OLED ─┘   Lambda jobs (1 phút)  │
                │ API Gateway ─ Lambda api ─ SES (email)         │
 Trình duyệt ───┤ CloudFront ─ S3 (web)   Cognito (admin/kiosk)  │
                └────────────────────────────────────────────────┘
```

| Bạn cần | Ghi chú |
|---|---|
| Laptop Linux/macOS (hoặc WSL) | Chạy script deploy, mock ESP32, kiosk |
| Tài khoản AWS | Free plan 6 tháng dùng được; xem mục 9 nếu dịch vụ bị chặn |
| Node.js ≥ 20, Python ≥ 3.11 | `node -v`, `python3 -V` |
| Pi 5 + camera | Đang chạy Smart Lighting — script tự nhường camera |

---

## 1. Cài AWS CLI và đăng nhập (laptop, ~10 phút)

```bash
# Linux x86_64 (macOS: tải gói .pkg trên trang AWS CLI)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip && sudo ./aws/install && aws --version
```

Tạo khóa truy cập — **không dùng khóa của tài khoản root**:

1. AWS Console → **IAM** → *Users* → *Create user*, tên `smart-parking-deployer`.
2. *Attach policies directly* → chọn `AdministratorAccess` (đồ án, xóa user sau khi xong).
3. Vào user → *Security credentials* → *Create access key* → *Command Line Interface*.
4. Trên laptop:
   ```bash
   aws configure
   # AWS Access Key ID / Secret: dán từ bước 3
   # Default region name: ap-southeast-1      (Singapore, gần VN, có đủ IoT Core/SES)
   # Default output format: json
   aws sts get-caller-identity               # phải in ra Account ID
   ```

## 2. Deploy backend (laptop, ~10 phút, chủ yếu chờ CloudFront)

```bash
cd ~/Code/Cloud-Course/infra/aws
./deploy.sh
```

Script hỏi 2 email (gửi chỉ dẫn cho khách; nhận cảnh báo chi phí) rồi tự: tạo bucket code, đóng gói Lambda, dựng stack `smart-parking-dev`, tạo 18 ô + bảng giá, ghi `web/.env.production.local`. Mọi giá trị riêng (email, khóa ký QR) lưu ở `secrets/deploy.env` — thư mục này **không commit**.

Ngay sau đó:

1. **Mở hộp thư email gửi** và bấm link *Amazon Web Services – Email Address Verification Request*. Chưa bấm thì SES không gửi được thư.
2. **SES sandbox**: tài khoản mới chỉ gửi được tới email *đã xác minh*. Để demo, xác minh thêm email của các thành viên:
   ```bash
   aws sesv2 create-email-identity --email-identity ban-cung-nhom@gmail.com
   ```
   Muốn khách nhập email bất kỳ: SES Console → *Account dashboard* → *Request production access* (duyệt ~1 ngày).
3. Tạo tài khoản đăng nhập web:
   ```bash
   ./create-users.sh            # hỏi mật khẩu cho 'admin' (nhóm ADMIN) và 'kiosk' (nhóm KIOSK)
   ```

> Nếu bước deploy lỗi ở `WebDistribution` (tài khoản mới chưa được dùng CloudFront): chạy `ENABLE_CDN=false WEB_BASE_URL_OVERRIDE=http://<ip-laptop>:5173 ./deploy.sh`, sau đó chạy web trên laptop (mục 4, cách B).

## 3. Cấp cert cho 3 thiết bị (laptop, 1 phút)

```bash
./provision-devices.sh
# hoặc điền sẵn Wi-Fi cho ESP32 ngày mai:
WIFI_SSID="TenWifi" WIFI_PASS="matkhau" ./provision-devices.sh
```

Tạo 3 IoT Thing `pi-01`, `gate-01`, `slots-01`, mỗi cái một certificate + policy chỉ được dùng đúng topic của nó, và sinh:

| File | Dùng cho |
|---|---|
| `secrets/certs/<thiết bị>/cert.pem, private.key` | mock trên laptop |
| `edge/raspberry-pi-vision/config.local.toml` | Pi |
| `firmware/esp32-*/include/secrets.h` | ESP32 (ngày 2) |

## 4. Đưa web lên (laptop)

**Cách A — CloudFront (mặc định):**
```bash
./deploy-web.sh          # build + upload S3 + làm mới cache, in ra URL https://dxxxx.cloudfront.net
```

**Cách B — chạy trên laptop** (khi không dùng CloudFront, hoặc đang sửa giao diện):
```bash
cd ~/Code/Cloud-Course/web && npm install && npm run dev      # http://<ip-laptop>:5173, gọi API thật
```

| Trang | Ai dùng | Đăng nhập |
|---|---|---|
| `/` | sơ đồ 18 ô công khai | không |
| `/kiosk` | laptop/tablet đặt ở cổng vào, hiện QR lớn | `kiosk` |
| `/admin` | quản trị: cảnh báo, thiết bị, mở cần tay, phiên, thu tiền, bảng giá | `admin` |
| `/s/<token>` | điện thoại khách sau khi quét QR | không |

## 5. Chạy 2 ESP32 bằng script (laptop) — ngày 1

Mở **hai terminal**:

```bash
cd ~/Code/Cloud-Course
python3 -m venv .venv && .venv/bin/pip install -r simulation/requirements.txt

# Terminal 1 — giả lập gate-01 (2 cần + OLED in ra màn hình)
.venv/bin/python simulation/mock_gate.py

# Terminal 2 — giả lập slots-01 (gõ F1-A1 hoặc số 0–17 để đảo ô)
.venv/bin/python simulation/mock_slots.py
```

Mở `/admin` → *Thiết bị*: `gate-01` và `slots-01` phải **ONLINE**; sơ đồ `/` chuyển từ xám (UNKNOWN) sang xanh.
Mock dùng **đúng cert, client id, topic, JSON** như firmware, nên backend không phân biệt được mock và board thật.

> Mạng trường/quán cà phê hay chặn cổng 8883. Thấy mock báo "chưa kết nối được": chạy `IOT_PORT=443 .venv/bin/python simulation/mock_gate.py` (MQTT qua cổng 443).

Giả một xe ở làn khi chưa có Pi (dùng biển số bạn đặt; lượt sẽ chờ quản trị bấm Cho vào / Cho ra trên `/admin/sessions`):

```bash
.venv/bin/python simulation/fake_car.py vao 51A-12345     # có xe ở làn vào
.venv/bin/python simulation/fake_car.py ra  51A-12345     # có xe ở làn ra
```

Có Pi thì dùng nút **Thử xe VÀO / Thử xe RA** trên trang camera `http://<ip-pi>:8000` (biển demo do backend đánh).

Nút "Mở tay" trên admin chỉ nhấc cần để thử cơ khí, không tạo lượt xe nên không có QR.

## 6. Kiểm thử đầu cuối không cần camera (laptop, 1 phút)

Khi mock đang chạy và **pi-vision trên Pi chưa bật** (script mượn client id `pi-01`):

```bash
.venv/bin/python simulation/e2e_smoke.py
```

> **Chưa cập nhật theo luồng mới** (cho vào/cho ra bằng tay, không gán ô): script này viết cho luồng cũ nên sẽ dừng ở bước kiểm tra ô được gán. Dùng kịch bản tay ở mục 8; kiểm thử nghiệp vụ tự động nằm ở `backend/tests` (`python -m pytest -q`).

## 7. Pi 5: nhường camera và nối AWS

### 7.1 Pi phải ra được internet

Dự án Smart Lighting cấu hình `wlan0` của Pi **phát Wi-Fi `Oi-Net`** — khi đó Wi-Fi không còn dùng để lên mạng. Kiểm tra trên Pi:

```bash
curl -sS -o /dev/null --max-time 8 https://aws.amazon.com && echo "CÓ INTERNET"   # amazon.com chặn ping nên không dùng ping
nmcli -t -f NAME,DEVICE connection show --active
```

Không có internet thì chọn một:

- **Cắm dây LAN** từ router vào Pi (khuyên dùng): Pi lên mạng qua `eth0`, `Oi-Net` vẫn chạy cho đèn. Vì `oi-ap` dùng `ipv4.method shared`, thiết bị nối `Oi-Net` (kể cả ESP32 ngày mai) cũng ra được internet qua Pi.
- **Cắm dây LAN thẳng từ laptop vào Pi** (ở trường, không có router): cho laptop **chia sẻ Internet** qua cổng LAN. Laptop (Ubuntu/NetworkManager, profile dây tên `Profile 1`):
  ```bash
  nmcli connection modify "Profile 1" ipv4.method shared ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
  nmcli connection up "Profile 1"
  ip neigh show dev enp3s0        # IP của Pi, thường 10.42.0.x (ví dụ 10.42.0.105)
  ssh oi@10.42.0.105
  ```
  Laptop thành `10.42.0.1`, tự cấp IP cho Pi và chia Internet đang có (Wi-Fi trường) cho Pi. Về mạng nhà cần IP tĩnh cũ: `nmcli connection modify "Profile 1" ipv4.method manual ipv4.addresses 192.168.0.100/24`.
- **Tạm tắt điểm phát** (làm qua dây LAN/màn hình, *không* qua SSH Wi-Fi): `sudo nmcli connection down oi-ap && sudo nmcli device wifi connect "<WiFi>" password "<mật khẩu>"`. Bật lại đèn: `sudo nmcli connection up oi-ap`.

### 7.2 Đưa code và cert lên Pi

**Nhanh nhất — một lệnh từ laptop** (làm luôn 7.2 và phần cài của 7.3):
```bash
cd ~/Code/Cloud-Course/infra/aws && ./setup-pi.sh <user>@<ip-pi>
```
Rồi SSH vào Pi chạy `./pi-mode.sh parking` (mục 7.3). Làm tay từng bước:

```bash
# Trên Pi (lần đầu)
git clone https://github.com/Tuyen230605/Smart_parking.git ~/Cloud-Course
# hoặc từ laptop, không cần push:  rsync -a --exclude node_modules --exclude secrets ~/Code/Cloud-Course/ <user>@<ip-pi>:~/Cloud-Course/

# Trên laptop: chép cert pi-01 + config.local.toml
cd ~/Code/Cloud-Course/infra/aws && ./copy-pi-certs.sh <user>@<ip-pi>
```

### 7.3 Cài và chuyển camera sang Smart Parking

```bash
# Trên Pi
cd ~/Cloud-Course/edge/raspberry-pi-vision
./install-pi.sh                 # apt + venv + unit systemd pi-vision (chưa bật)
./pi-mode.sh status             # xem ai đang giữ camera
./pi-mode.sh parking            # dừng container vision của Lighting, bật pi-vision
journalctl -u pi-vision -f      # phải thấy "Đã kết nối MQTT"
```

- Pi chỉ có **một camera** và libcamera chỉ cho **một tiến trình** giữ nó, nên không chạy song song được. `pi-mode.sh parking` chỉ dừng container `vision`; broker, dashboard, policy… của Smart Lighting vẫn chạy.
- Container Lighting có `restart: unless-stopped`: đã `docker stop` thì **khởi động lại Pi vẫn không tự chạy lại**; pi-vision được `enable` nên tự chạy khi bật Pi. Trả camera: `./pi-mode.sh lighting`.
- Nếu `pi-mode.sh status` vẫn thấy tiến trình khác giữ `/dev/media*` (ví dụ một systemd unit của Lighting): `LIGHTING_UNITS="ten-unit.service" ./pi-mode.sh parking`.
- Không cài `mosquitto` lên Pi: cổng 1883 đang thuộc broker của Lighting và Smart Parking không cần broker local.

### 7.4 Hiệu chỉnh camera

Mở `http://<ip-pi>:8000` (cổng 8000 không trùng các cổng 80/1880/8090/9001 của Lighting). Click lấy ROI/HSV, sửa `config.toml`, rồi `sudo systemctl restart pi-vision`. Chi tiết: [edge/raspberry-pi-vision/README.md](../edge/raspberry-pi-vision/README.md#hiệu-chỉnh-trên-sa-bàn).

## 8. Kịch bản demo trọn vẹn

Chuẩn bị: Pi bật và nối dây LAN laptop (mục 7.1), ESP32 cổng và ESP32 ô cắm điện, cùng Wi-Fi 2.4 GHz có Internet. Mở `/admin` → *Tổng quan*: `pi-01`, `gate-01`, `slots-01` **ONLINE**.

1. Màn hình A mở `/kiosk` (đăng nhập `kiosk`, *Toàn màn hình*). Màn hình B mở `/admin/sessions` (lọc *Đang mở*). Có thể mở thêm trang camera `http://<ip-pi>:8000`.
2. **Đưa tay vào nửa trái khung camera** (làn vào) → trang Phiên đỗ hiện **"Chờ cho vào" xe `11111`**; OLED `XE 11111 / Cho nhan vien`; trang camera hiện "Chờ cho vào: 11111".
3. Admin bấm **Cho vào (mở cần vào)** → servo quay trái rồi tự về giữa sau 5 giây; xe vào danh sách xe trong bãi; OLED hiện ô gợi ý; kiosk hiện QR + bản đồ đường đi.
4. Điện thoại quét QR → **chạm chọn một ô trống** (thử ô tầng 2 để thấy bước lên ram) → nhập email đã xác minh SES, tùy chọn **Ghi nhớ email cho biển số** → nhận thư chỉ dẫn.
5. Bấm nút của ô vừa đỗ trên sa bàn → sơ đồ `/` chuyển ô đó sang *Có xe*.
6. **Đưa tay vào nửa phải khung camera** (làn ra) → Phiên đỗ hiện **"Chờ cho ra"** xe số lớn nhất + phí. Dưới 15 phút: bấm **Cho ra (mở cần)**; trên 15 phút: **Đã thu X ₫ → cho ra**. Servo quay phải; xe rời danh sách; phiên đóng. Bấm lại nút ô → ô về trống.
7. (Nếu đã ghi nhớ email) cho xe vào lại: biển demo lại là `11111` → bấm Cho vào → email chỉ dẫn **tự gửi**. Thử xong bấm *Bỏ liên kết email* trên trang QR (biển demo được dùng lại cho xe khác).

Kịch bản lỗi: bấm đủ 18 nút ô rồi cho xe vào → *Bãi đã đầy*, OLED `BAI DA DAY`; rút điện ESP ô > 90 giây → ô UNKNOWN nhưng xe vẫn được cho vào; tay giữ lâu trong khung chỉ tạo một lượt.

## 9. Ngày 2: nạp code vào 2 ESP32

```bash
pip install platformio            # hoặc cài extension PlatformIO trong VS Code
# Kiểm tra secrets.h đã có Wi-Fi đúng (mục 3). ESP32 chỉ dùng Wi-Fi 2.4 GHz.
```

1. **Tắt mock tương ứng trước** (Ctrl+C) — AWS IoT ngắt kết nối cũ khi hai bên dùng chung client id, hai bên sẽ đá nhau liên tục.
2. Board cổng — đấu nối theo đầu file [firmware/esp32-gates/src/main.cpp](../firmware/esp32-gates/src/main.cpp): ESP32-S3 + **một** servo SG90 tín hiệu GPIO18 (giữa = đóng, trái 90° = vào, phải 90° = ra), OLED tuỳ chọn SDA8/SCL9. **Nguồn servo:** chân ghi `5Vin` trên nhiều board S3 **không có điện khi cấp qua USB** (cần nối miếng hàn `IN-OUT`) → lấy 5 V từ Pi (chân 2) hoặc nguồn riêng, **nối GND chung** với ESP. Mỗi lần khởi động servo tự quay thử 150° → 30° → 90°: không thấy quay là thiếu nguồn/sai dây.
   ```bash
   cd firmware/esp32-gates && pio run -t upload && pio device monitor
   ```
3. Board ô — [firmware/esp32-slot-sensors/src/main.cpp](../firmware/esp32-slot-sensors/src/main.cpp): ESP32 thường, **18 nút nối thẳng GPIO** ↔ GND (pull-up trong chip), bảng chân ở [parking-layout.md](parking-layout.md#ánh-xạ-18-nút--gpio-esp32-thường-slots-01). Chân chưa cắm nút coi như chưa nhấn.
   ```bash
   cd firmware/esp32-slot-sensors && pio run -t upload && pio device monitor
   ```
4. Serial phải in `[mqtt] ✓ đã kết nối AWS IoT` và **không** lặp lại dòng "kết nối…" mỗi 2 giây. Chỉnh `ANGLE_CENTER/ENTRY_OPEN/EXIT_OPEN` theo cơ khí cần chắn.
5. Chạy lại mục 6 hoặc mục 8.

Thiếu OLED board cổng vẫn chạy và báo `DEGRADED` trên admin. Đổi Wi-Fi: sửa `WIFI_SSID`/`WIFI_PASS` trong `include/secrets.h` (mạng mở để `""`) rồi nạp lại.

## 10. Chi phí, xóa tài nguyên, sự cố

**Chi phí:** stack dùng dịch vụ tính theo lượt (Lambda, DynamoDB on-demand, HTTP API, IoT Core). Lượng phát sinh chính là snapshot 30 giây và heartbeat của 3 thiết bị + job giám sát mỗi phút — rất nhỏ so với 200 USD credit của Free plan, nhưng **AWS Budget** vẫn được tạo (mặc định 5 USD/tháng) để gửi email cảnh báo. Khi không demo nhiều ngày, tắt mock/thiết bị là gần như không tốn gì. Free plan mà chặn dịch vụ nào thì Console sẽ báo; nâng lên Paid plan vẫn dùng credit còn lại.

**Xóa sạch sau khi bảo vệ:** `cd infra/aws && ./destroy.sh`.

| Hiện tượng | Kiểm tra |
|---|---|
| Mock/Pi/ESP không kết nối | `secrets/iot.json` đúng region? Đồng hồ máy đúng giờ? Thử cổng 443. Xem *AWS IoT → Monitor* |
| Thiết bị ONLINE nhưng sơ đồ toàn xám | mock_slots chưa gửi snapshot: gõ `s` |
| Có xe ở làn vào nhưng không mở cần | Cần quản trị bấm **Cho vào** trên Phiên đỗ; xem Cảnh báo `LOT_FULL`, `DEVICE_OFFLINE` |
| Log ESP có `[servo] → 180°` mà servo không quay | Thiếu nguồn 5 V cho servo (chân `5Vin`), xem mục 9 |
| ESP kết nối AWS rồi bị ngắt mỗi 2 giây | Firmware cũ subscribe topic rỗng → nạp lại firmware mới |
| Web báo `UNAUTHENTICATED` | Đăng xuất/đăng nhập lại; chạy lại `./create-users.sh` |
| Email `FAILED` | Sender chưa xác minh hoặc người nhận chưa xác minh (sandbox) |
| Xem log backend | `aws logs tail /aws/lambda/smart-parking-dev-iot --follow` (tương tự `-api`, `-jobs`) |
| Theo dõi MQTT trực tiếp | AWS IoT Console → *MQTT test client* → subscribe `parking/v1/site-01/#` |
| Pi: `Camera ... in use` | `./pi-mode.sh status`, còn tiến trình Lighting giữ camera |
