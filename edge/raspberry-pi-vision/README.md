# Raspberry Pi vision

Module camera, phát hiện thẻ màu, OCR biển số và publish sự kiện theo [hợp đồng MQTT](../../docs/mqtt-contract.md).

Đầu ra tối thiểu: `event_id`, `type`, `lane_id`, `card_color`, `plate`, `plate_confidence`, `captured_at`.

Không ghi credential vào mã nguồn. Khi phát triển, dùng video/ảnh fixture; cấu hình camera và broker qua biến môi trường hoặc file cấu hình local bị gitignore.
