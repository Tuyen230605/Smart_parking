# Raspberry Pi 5: camera phát hiện xe ở làn vào/ra

Bản demo **không dùng thẻ màu hay biển in**. Một camera nhìn hai khung làn (mặc định nửa trái = `ENTRY`, nửa phải = `EXIT`). Pi so mỗi khung với ảnh nền trống; khi có vật (bàn tay, xe mô hình) che vào đủ lâu thì publish **một** `vehicle_detected` (`plate_text = null`) theo [MQTT v1](../../docs/mqtt-contract.md). Backend đánh biển demo (`11111`, `22222`…), chờ quản trị bấm **Cho vào / Cho ra** trên web rồi mới mở cần, và gửi lại **danh sách xe trong bãi** để trang camera hiển thị. Pi không tự mở cần, không giữ danh sách riêng.

Ảnh chỉ xử lý trong RAM, không upload cloud.

## Pipeline

```text
Picamera2 (1920x1080 cho OV5647, 10 fps)
  → mỗi khung làn: thu nhỏ, xám, làm mờ; so với ảnh nền (bù chênh sáng toàn khung)   (presence.LanePresence)
  → tỉ lệ điểm ảnh khác nền ≥ min_ratio trong stable_frames frame → báo 1 lượt
  → phải trống clear_frames frame (và cách cooldown_s) mới nhận lượt mới; vật nằm yên > absorb_after_s thì nhập vào nền
  → publish vehicle_detected (QoS 1): ENTRY+GREEN / EXIT+RED, plate_text = null
  → subscribe parking/v1/site-01/vision/pi-01/lot ← backend gửi danh sách xe (trong bãi / chờ vào / chờ ra)
  → device_status mỗi 30 giây, Last Will OFFLINE
```

| File | Vai trò |
|---|---|
| `config.toml` | Khung làn `lanes.*.roi`, ngưỡng `[presence]`, camera, MQTT |
| `main.py` | Vòng lặp chính, nút thử trên trang preview |
| `presence.py` | Phát hiện vật trong làn bằng so nền |
| `cars.py` | `LotView`: danh sách xe backend gửi xuống (chỉ hiển thị) |
| `camera.py` | Picamera2, webcam, video hoặc ảnh tĩnh |
| `publisher.py` | Message đúng schema v1; subscribe danh sách xe |
| `preview.py` | Trang `http://<ip-pi>:8000`: video có vẽ khung làn, danh sách xe, nút **Thử xe VÀO / RA**, **Chụp lại nền** |
| `test_presence.py` | Test phát hiện vật và hiển thị danh sách: `python -m unittest test_presence` |
| `detector.py`, `mock_pi.py`, `make_fixtures.py`, `test_detector.py` | Bản cũ (thẻ màu + OCR RapidOCR), giữ để tham khảo; `main.py` chỉ dùng `crop`/`roi_to_pixels` |

## Cài đặt trên Pi 5

1. Raspberry Pi Imager → Raspberry Pi OS (64-bit) → *Edit settings*: hostname, user, Wi-Fi, bật SSH (Pi của nhóm: hostname `oi`, user `oi`). Từ laptop: `ssh oi@<ip-pi>`; nối dây LAN thẳng laptop thì xem [setup-guide §7.1](../../docs/setup-guide.md#71-pi-phải-ra-được-internet). Muốn xem desktop: `sudo apt install rpi-connect && rpi-connect signin` rồi mở connect.raspberrypi.com, hoặc bật VNC trong `sudo raspi-config`.
2. Kiểm tra camera:
   ```bash
   rpicam-hello --list-cameras
   rpicam-still -o test.jpg
   ```
3. Cài môi trường:
   ```bash
   sudo apt update && sudo apt install -y git python3-picamera2 python3-opencv mosquitto mosquitto-clients
   git clone <repo> ~/Cloud-Course && cd ~/Cloud-Course/edge/raspberry-pi-vision
   python3 -m venv --system-site-packages ~/venv
   ~/venv/bin/pip install -r requirements.txt
   ~/venv/bin/python -m unittest test_detector
   ```
4. Chạy với Mosquitto local và mở `http://<ip-pi>:8000` trên laptop:
   ```bash
   mosquitto_sub -v -t 'parking/#' &      # xem message được gửi
   ~/venv/bin/python main.py
   ```

## Hiệu chỉnh trên sa bàn

1. Đặt camera nhìn mặt bãi, ánh sáng ổn định. Trên trang preview, click hai góc vùng làn vào/ra rồi ghi tọa độ vào `lanes.*.roi` = `[x, y, rộng, cao]`.
2. Khung làn: xám = `TRONG`, cam = `THAY VAT` (đang đếm frame), xanh = `DA BAO` (đã gửi lượt, chờ rút tay). Nhãn có % diện tích khác nền.
3. Đổi chỗ/góc camera thì bỏ tay ra rồi bấm **Chụp lại nền**.
4. Tay nhỏ so với khung → giảm `min_ratio`; báo nhầm khi không có gì → tăng `diff_threshold` hoặc `min_ratio`.
5. Sửa `config.toml` xong khởi động lại dịch vụ (`sudo systemctl restart pi-vision`; không có quyền sudo thì `kill $(systemctl show -p MainPID --value pi-vision)`, systemd tự chạy lại).

## Kết nối AWS IoT Core

Tạo Thing `pi-01` (thường do người 4 làm, Pi chỉ cần ba file):

```bash
aws iot create-thing --thing-name pi-01
aws iot create-keys-and-certificate --set-as-active \
  --certificate-pem-outfile pi-01.cert.pem --private-key-outfile pi-01.private.key
aws iot create-policy --policy-name pi-01-policy --policy-document file://policy.json
aws iot attach-policy --policy-name pi-01-policy --target <certificateArn>
aws iot attach-thing-principal --thing-name pi-01 --principal <certificateArn>
aws iot describe-endpoint --endpoint-type iot:Data-ATS
curl -o AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem
```

`policy.json` chỉ cho `pi-01` kết nối và publish hai topic của mình:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "iot:Connect", "Resource": "arn:aws:iot:<region>:<account>:client/pi-01"},
    {"Effect": "Allow", "Action": "iot:Publish", "Resource": [
      "arn:aws:iot:<region>:<account>:topic/parking/v1/site-01/vision/pi-01/events",
      "arn:aws:iot:<region>:<account>:topic/parking/v1/site-01/devices/pi-01/status"
    ]}
  ]
}
```

Chép cert vào `/etc/parking/certs/` (ngoài repo, `chmod 600` file key), rồi sửa `[mqtt]`: `host` = endpoint ATS, `port = 8883`, `tls = true`. Kiểm tra bằng MQTT test client trên AWS Console, subscribe `parking/v1/site-01/#`.

## Chạy tự động khi khởi động (cùng Pi với Smart Lighting)

```bash
./install-pi.sh            # apt + venv ~/venv-parking + unit pi-vision theo user hiện tại
./pi-mode.sh parking       # dừng container vision của Lighting (giữ camera), bật pi-vision
./pi-mode.sh lighting      # trả camera cho Lighting
journalctl -u pi-vision -f
```

`config.local.toml` (do `infra/aws/provision-devices.sh` sinh, `infra/aws/copy-pi-certs.sh` chép sang) ghi đè `[mqtt]` của `config.toml` để nối AWS IoT. Mạng chặn 8883 thì đặt `port = 443` (dùng ALPN). Xem [setup-guide](../../docs/setup-guide.md#7-pi-5-nhường-camera-và-nối-aws).

## Thử trên laptop không cần Pi

```bash
pip install paho-mqtt opencv-python-headless numpy
python -m unittest test_presence
python main.py --source 0 --dry-run                     # webcam laptop, preview tại http://localhost:8000
```
