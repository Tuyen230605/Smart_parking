# Mô phỏng

Mock dùng **đúng cert, client id, topic và JSON** của thiết bị thật ([MQTT v1](../docs/mqtt-contract.md)), nối thẳng AWS IoT Core bằng file do `infra/aws/provision-devices.sh` sinh. Thêm `--local` để dùng Mosquitto `localhost:1883`.

| Script | Thay cho | Dùng |
|---|---|---|
| `mock_gate.py` | ESP32 `gate-01` | Nhận lệnh cần/OLED, kiểm hạn/trùng/đích, ACK `OPENING→OPEN→CLOSING→CLOSED`. `--hold 5`, `--fail-motor`, `--no-ack` |
| `mock_slots.py` | ESP32 `slots-01` | Gõ `F1-A1` hoặc `0–17` để đảo ô; `s` snapshot; `full`/`clear`; `off 100` ngắt mạng 100 s. Lưu trạng thái như NVS |
| `fake_car.py` | camera Pi `pi-01` | `fake_car.py vao 51A-12345` / `fake_car.py ra 51A-12345`: một xe quẹt thẻ, dùng để demo QR/cần khi chưa bật Pi |
| `e2e_smoke.py` | — | Một lượt vào → đỗ → ra → đóng phiên trên AWS thật, qua API admin |
| `../edge/raspberry-pi-vision/mock_pi.py` | Pi `pi-01` | Sự kiện camera theo kịch bản |

```bash
pip install -r simulation/requirements.txt
python simulation/mock_gate.py      # terminal 1
python simulation/mock_slots.py     # terminal 2
python simulation/e2e_smoke.py      # terminal 3 (tắt pi-vision trước: cùng client id pi-01)
```

AWS IoT chỉ giữ một kết nối mỗi client id: khi đã nạp ESP32 thật, tắt mock tương ứng. 16 kịch bản nghiệm thu: [simulation-and-test-plan.md](../docs/simulation-and-test-plan.md).
