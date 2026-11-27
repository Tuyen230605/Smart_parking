# Phân công

| Thành viên | MSSV | Đóng góp | Phần việc chính |
|---|---|---|---|
| Đoàn Văn Tuyền | 23020151 | 31% | Hạ tầng AWS, Raspberry Pi, web |
| Phạm Ngọc Hải Đăng | 24022771 | 23% | Phần xử lý trên đám mây (Lambda, DynamoDB, API) |
| Nguyễn Văn Khoa | 23020829 | 23% | ESP32 đọc 18 nút giả lập cảm biến ô, tích hợp firmware |
| Lê Hoàng Vũ | 23020898 | 23% | ESP32-S3 điều khiển cần chắn, tích hợp firmware |

## Phần việc theo thư mục

| Thư mục | Người phụ trách |
|---|---|
| `infra/aws/`, `edge/raspberry-pi-vision/`, `web/` | Tuyền |
| `backend/` | Đăng |
| `firmware/esp32-slot-sensors/`, `firmware/common/` | Khoa |
| `firmware/esp32-gates/`, `firmware/common/` | Vũ |
| `docs/`, `report/` | Cả nhóm |

## Quy ước làm việc chung

- Định dạng tin nhắn MQTT ([mqtt-contract.md](mqtt-contract.md)) và API ([api-contract.md](api-contract.md)) được chốt trước. Ai đổi thì sửa tài liệu cùng lúc với code và báo cả nhóm.
- Trong lúc chưa có phần cứng, mỗi người dùng chương trình giả lập trong `simulation/` để thử phần của mình với AWS thật.
- Chạy kiểm thử trước khi đẩy code: `cd backend && ../.venv/bin/python -m pytest -q tests`.
- Không commit khóa, chứng chỉ, mật khẩu Wi-Fi.
