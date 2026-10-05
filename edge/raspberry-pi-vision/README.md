# Raspberry Pi 5: camera và nhận diện

Một camera chụp cả hai ROI `ENTRY`/`EXIT`. Thẻ xanh chỉ hợp lệ ở làn vào, thẻ đỏ chỉ hợp lệ ở làn ra. Pi phát hiện màu ổn định qua nhiều frame, OCR biển số tại chỗ và publish `vehicle_detected` theo [MQTT v1](../../docs/mqtt-contract.md). OCR yếu/sai làn vẫn gửi sự kiện để backend chuyển quản trị xác nhận; Pi không tự mở cần.

MVP xử lý ảnh trong RAM, không upload ảnh cloud. Cần có bộ ảnh/video fixture giả lập và báo cáo góc camera, ánh sáng, confidence, tỷ lệ đọc đúng. Một camera không đủ rõ hai làn thì demo tuần tự từng làn với cùng schema.
