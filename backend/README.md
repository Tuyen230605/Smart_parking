# Backend

Mã Python cho 3 hàm Lambda. Backend là nơi duy nhất ra quyết định: tạo phiên đỗ, cấp biển số demo, tính tiền, gửi lệnh mở cần, gửi email và gửi danh sách xe cho Pi. Dữ liệu lưu ở DynamoDB.

## Các tệp

| Tệp | Nội dung |
|---|---|
| `src/iot_handler.py` | Lambda `iot`: nhận tin nhắn từ thiết bị qua IoT Rule, chuyển tới hàm xử lý phù hợp |
| `src/api_handler.py` | Lambda `api`: các API cho web, kiểm tra nhóm quyền, chống gửi lặp |
| `src/jobs.py` | Lambda `jobs`: giám sát mỗi phút, dọn dữ liệu quá 10 ngày mỗi giờ, tạo dữ liệu ban đầu khi triển khai |
| `src/logic.py` | Nghiệp vụ: chờ vào, cho vào, chờ ra, cho ra, tính tiền, gợi ý ô, danh sách xe, tự gửi email theo biển số |
| `src/services.py` | Ký link QR, bảng giá, gửi lệnh MQTT, gửi email SES |
| `src/core.py` | Truy cập bảng, thời gian, mã, biển số demo, cảnh báo |

Chỉ dùng thư viện `boto3` có sẵn trên Lambda nên không cần build. Cách triển khai xem [infra/aws](../infra/aws/README.md).

## Luồng chính

- Pi báo có xe ở làn vào: tạo phiên "chờ cho vào" với biển số demo.
- Nhân viên bấm Cho vào: một giao dịch DynamoDB đổi phiên sang "đang đỗ" và khóa biển số; sau đó gửi lệnh mở cần, cấp mã QR, tự gửi email nếu biển số đã ghi nhớ email.
- Pi báo có xe ở làn ra: chọn xe số lớn nhất đang đỗ, chốt số tiền, chuyển sang "chờ cho ra".
- Nhân viên bấm Cho ra (sau khi thu tiền nếu có phí): gửi lệnh mở cần, đóng phiên.

Mọi tin nhắn và thao tác có mã riêng nên gửi lặp không bị xử lý hai lần.

## Kiểm thử

```bash
python3 -m venv .venv && .venv/bin/pip install pytest "moto[dynamodb]" boto3
cd backend && ../.venv/bin/python -m pytest -q tests
```

16 kịch bản chạy với DynamoDB giả lập, không cần AWS: vào, ra, tính tiền, bãi đầy, gửi lặp, mất kết nối, email, ghi nhớ email, phân quyền, SES lỗi, dọn dữ liệu.
