# Giả lập thiết bị

Dùng khi chưa có phần cứng. Các chương trình này dùng đúng chứng chỉ, tên thiết bị, kênh và định dạng tin nhắn như thiết bị thật ([quy ước MQTT](../docs/mqtt-contract.md)), nên AWS không phân biệt được.

| Chương trình | Thay cho | Cách dùng |
|---|---|---|
| `mock_gate.py` | ESP32-S3 cần chắn | In ra trạng thái cần khi nhận lệnh. Tùy chọn: `--hold 5`, `--fail-motor`, `--no-ack` |
| `mock_slots.py` | ESP32 18 nút | Gõ `F1-A1` hoặc số 0–17 để đảo một ô; `s` gửi trạng thái ngay; `full` hoặc `clear` để đổi tất cả |
| `fake_car.py` | Camera của Pi | `fake_car.py vao 51A-12345` hoặc `fake_car.py ra 51A-12345` |

```bash
python3 -m venv .venv && .venv/bin/pip install -r simulation/requirements.txt
.venv/bin/python simulation/mock_gate.py    # cửa sổ 1
.venv/bin/python simulation/mock_slots.py   # cửa sổ 2
```

Chứng chỉ lấy từ `secrets/` do `infra/aws/provision-devices.sh` sinh ra. Thêm `--local` để dùng máy chủ MQTT trên máy (`localhost:1883`). Mạng chặn cổng 8883 thì thêm `IOT_PORT=443` trước lệnh.

AWS chỉ cho mỗi tên thiết bị một kết nối. Khi đã cắm thiết bị thật thì tắt chương trình giả lập tương ứng.
