# Mô phỏng

Mock Pi, ESP gate và ESP slots phải dùng đúng [MQTT v1](../docs/mqtt-contract.md). Mock slots có đủ 18 ô; F1-A1 giả lập tín hiệu cảm biến khi chạy không có sa bàn, 17 ô khác giả lập nút. Mock gate trả ACK cho hai cần/OLED, cho phép tạo lỗi/timeout/replay.

Xem [16 kịch bản nghiệm thu](../docs/simulation-and-test-plan.md). Hiện thư mục là khung tài liệu; script mô phỏng sẽ được nhóm phát triển ở các mốc trong [kế hoạch](../PROJECT_PLAN.md).
