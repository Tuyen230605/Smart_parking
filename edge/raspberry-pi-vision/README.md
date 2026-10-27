# Raspberry Pi 5: camera và nhận diện

Một camera chụp cả hai ROI `ENTRY`/`EXIT`. Thẻ xanh chỉ hợp lệ ở làn vào, thẻ đỏ chỉ hợp lệ ở làn ra. Pi phát hiện màu ổn định qua nhiều frame, OCR biển số tại chỗ và publish `vehicle_detected` theo [MQTT v1](../../docs/mqtt-contract.md). OCR yếu/sai làn vẫn gửi sự kiện để backend chuyển quản trị xác nhận; Pi không tự mở cần.

MVP xử lý ảnh trong RAM, không upload ảnh cloud. Cần có bộ ảnh/video fixture giả lập và báo cáo góc camera, ánh sáng, confidence, tỷ lệ đọc đúng. Một camera không đủ rõ hai làn thì demo tuần tự từng làn với cùng schema.

## Pipeline

```text
Picamera2 (2304x1296, 10 fps)
  → mỗi ROI làn: lọc HSV → GREEN / RED / không có thẻ        (detector.CardDetector)
  → cùng màu stable_frames frame liên tiếp                     (detector.LaneTracker)
  → OCR vùng biển số bằng RapidOCR (ONNX, CPU) tối đa ocr_attempts lần, lấy kết quả tốt nhất
  → chuẩn hóa 51A-12345; không khớp mẫu biển VN thì confidence ≤ 0,5
  → publish vehicle_detected (QoS 1) một lần; chờ thẻ rời ROI clear_frames frame mới nhận xe mới,
    cùng xe/làn không phát lại trong 5 giây
  → device_status mỗi 30 giây, Last Will OFFLINE
```

| File | Vai trò |
|---|---|
| `config.toml` | ROI, ngưỡng HSV, ngưỡng ổn định/OCR, MQTT |
| `main.py` | Vòng lặp chính |
| `camera.py` | Picamera2, webcam, video hoặc ảnh tĩnh |
| `detector.py` | Màu thẻ, OCR, chuẩn hóa biển số, bộ ổn định theo làn |
| `publisher.py` | Message đúng schema v1 (`event_id`, `boot_id`, `seq`) |
| `preview.py` | Trang xem camera trong LAN, click lấy tọa độ ROI/HSV |
| `mock_pi.py` | Phát kịch bản giả cho backend: `entry-ok`, `exit-ok`, `low-confidence`, `no-plate`, `wrong-lane`, `replay` |
| `make_fixtures.py` | Sinh ảnh tổng hợp trong `fixtures/` |

## Cài đặt trên Pi 5

1. Raspberry Pi Imager → Raspberry Pi OS (64-bit) → *Edit settings*: hostname `pi-01`, user, Wi-Fi, bật SSH. Từ laptop: `ssh <user>@pi-01.local`. Muốn xem desktop: `sudo apt install rpi-connect && rpi-connect signin` rồi mở connect.raspberrypi.com, hoặc bật VNC trong `sudo raspi-config`.
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
4. Chạy với Mosquitto local và mở `http://pi-01.local:8000` trên laptop:
   ```bash
   mosquitto_sub -v -t 'parking/#' &      # xem message được gửi
   ~/venv/bin/python main.py
   ```

## Hiệu chỉnh trên sa bàn

1. Trên trang preview, click hai góc vùng làn vào/ra rồi ghi tọa độ vào `lanes.*.roi` = `[x, y, rộng, cao]`. Khung ROI hiện màu xám khi trống, xanh/đỏ khi thấy thẻ; nhãn hiện trạng thái tracker và tỉ lệ màu `G=`/`R=`.
2. Click lên thẻ thật để đọc HSV; chỉnh `colors.*.ranges` sao cho thẻ vượt `min_card_ratio` mà mặt bãi, xe không vượt.
3. Nếu xe luôn dừng ở cùng chỗ, đặt `plate_roi` ôm sát biển số: OCR nhanh và chính xác hơn.
4. Biển số in một dòng, font đậm, nền trắng; trong `/snapshot.jpg` chữ cao ít nhất khoảng 30 px. Đèn chiếu ổn định, tránh lóa.
5. Chạy thử từng kịch bản: thẻ xanh ở làn vào, thẻ đỏ ở làn ra, thẻ sai làn, che biển số. Ghi số lần đọc đúng/tổng để báo cáo.

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

## Chạy tự động khi khởi động

```bash
sudo cp pi-vision.service /etc/systemd/system/   # sửa User và đường dẫn trước
sudo systemctl enable --now pi-vision
journalctl -u pi-vision -f
```

## Thử trên laptop không cần Pi

```bash
pip install -r requirements.txt opencv-python-headless
python make_fixtures.py
python main.py --source fixtures/both.jpg --dry-run     # preview tại http://localhost:8000
python main.py --source 0 --dry-run                     # webcam laptop
python mock_pi.py all --dry-run                         # fixture JSON cho backend
```
