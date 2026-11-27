# Raspberry Pi 5: phát hiện xe ở làn vào, làn ra

Chương trình `pi-vision` chạy trên Pi. Camera nhìn hai làn: nửa trái khung hình là làn vào, nửa phải là làn ra. Khi có vật (bàn tay, xe mô hình) che vào một làn đủ lâu, Pi gửi một tin "có xe" lên AWS IoT Core. Pi không đọc biển số, không tự mở cần. Biển số demo do đám mây cấp, và đám mây gửi lại danh sách xe để Pi hiện lên trang camera.

Ảnh chỉ xử lý trong bộ nhớ, không gửi lên mạng.

## Cách phát hiện xe

Mỗi giây chương trình xử lý 10 khung hình. Với từng làn:

1. Cắt vùng làn, thu nhỏ, chuyển sang ảnh xám, làm mờ nhẹ.
2. So với ảnh nền lúc làn trống (có bù chênh lệch độ sáng chung).
3. Nếu từ 8% diện tích làn trở lên khác nền trong 3 khung liên tiếp thì báo một lượt.
4. Làn phải trống 8 khung liên tiếp (và cách lượt trước ít nhất 3 giây) mới báo lượt tiếp theo. Vật nằm yên quá 15 giây được tính vào nền.

## Các tệp

| Tệp | Nội dung |
|---|---|
| `main.py` | Vòng lặp chính |
| `presence.py` | Phát hiện vật bằng so ảnh nền |
| `cars.py` | Giữ danh sách xe do đám mây gửi xuống để hiển thị |
| `camera.py` | Đọc ảnh từ camera Pi, webcam hoặc tệp ảnh. Không có camera thì vẫn chạy |
| `publisher.py` | Gửi, nhận tin nhắn MQTT |
| `preview.py` | Trang camera ở cổng 8000 |
| `settings.py` | Đọc `config.toml`, ghi đè bằng `config.local.toml` |
| `config.toml` | Vùng làn, độ nhạy, camera, MQTT |
| `test_presence.py` | Kiểm thử: `python -m unittest test_presence` |
| `install-pi.sh` | Cài thư viện và dịch vụ `pi-vision` |

`config.local.toml` do `infra/aws/provision-devices.sh` sinh ra, chứa địa chỉ IoT Core và đường dẫn chứng chỉ. Tệp này không được commit.

## Cài đặt

Cách nhanh nhất, chạy trên laptop: `cd infra/aws && ./setup-pi.sh oi@<ip-pi>`. Script lấy mã nguồn, chép chứng chỉ, chạy `install-pi.sh` và bật dịch vụ.

Làm tay trên Pi:

```bash
git clone https://github.com/Tuyen230605/Smart_parking.git ~/Cloud-Course
cd ~/Cloud-Course/edge/raspberry-pi-vision
./install-pi.sh                 # cài thư viện, tạo dịch vụ pi-vision và bật luôn
journalctl -u pi-vision -f      # phải thấy "Đã kết nối MQTT"
```

Chứng chỉ được chép từ laptop bằng `infra/aws/copy-pi-certs.sh oi@<ip-pi>`. Dịch vụ tự chạy mỗi khi bật Pi.

## Trang camera

Mở `http://<ip-pi>:8000` trên máy cùng mạng với Pi. Trang có:

- Hình camera với hai khung làn: xám là trống, cam là đang thấy vật, xanh là đã báo lượt.
- Danh sách xe trong bãi, xe chờ vào, xe chờ ra (lấy từ đám mây).
- Nút *Thử xe VÀO*, *Thử xe RA*: gửi đúng loại tin như camera, dùng khi chưa đặt camera.
- Nút *Chụp lại nền*: bấm sau khi đổi góc camera (nhớ bỏ tay ra khỏi khung).

Nếu camera chưa cắm hoặc cáp lỏng, trang vẫn chạy và hiện dòng "không có hình".

## Chỉnh cho đúng sa bàn

1. Bấm lên ảnh để xem tọa độ, rồi sửa `lanes.ENTRY.roi` và `lanes.EXIT.roi` trong `config.toml` theo dạng `[x, y, rộng, cao]` (giá trị 0–1).
2. Tay nhỏ so với khung làn thì giảm `min_ratio`. Báo nhầm khi không có gì thì tăng `diff_threshold` hoặc `min_ratio`.
3. Sửa xong thì khởi động lại dịch vụ: `sudo systemctl restart pi-vision`.

## Thử trên laptop

```bash
pip install paho-mqtt opencv-python-headless numpy
python -m unittest test_presence
python main.py --source 0 --dry-run   # dùng webcam, không gửi lên AWS, trang tại http://localhost:8000
```

## Sự cố

- Không có hình, log báo `Camera frontend has timed out`: tắt Pi, cắm lại cáp camera cho chặt. Pi 5 cần cáp 22 sang 15 chân, mặt có chân kim loại quay về phía cổng HDMI.
- Pi tự tắt sau vài phút: cáp camera lỏng hoặc nguồn yếu. Dùng nguồn 5 V/5 A.
- Kiểm tra Pi có thiếu điện không: `vcgencmd get_throttled` (kết quả `0x0` là ổn).
