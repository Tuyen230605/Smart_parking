# ESP32 cảm biến ô đỗ

Đọc một hoặc nhiều cảm biến, lọc nhiễu/debounce, ánh xạ input sang `slot_id`, rồi gửi trạng thái theo [hợp đồng MQTT](../../docs/mqtt-contract.md).

Cấu hình số ô và chân GPIO tách khỏi logic đọc cảm biến. Gửi timestamp, trạng thái, và confidence nếu cảm biến cung cấp được mức tin cậy.
