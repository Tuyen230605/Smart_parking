# ESP32 điều khiển cổng

Firmware điều khiển cần vào và cần ra, đọc trạng thái công tắc hành trình, nhận lệnh có thời hạn và báo telemetry theo [hợp đồng MQTT](../../docs/mqtt-contract.md).

Tách driver cơ cấu khỏi logic MQTT. Dùng nguồn riêng phù hợp cho servo/motor; nối mass chung theo thiết kế điện; không cấp tải motor từ GPIO. Xác minh hành trình, timeout, nút dừng và trạng thái khi mất mạng trước demo.
