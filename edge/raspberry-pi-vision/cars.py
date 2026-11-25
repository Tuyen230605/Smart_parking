"""Danh sách xe trong bãi do BACKEND gửi xuống (topic .../vision/pi-01/lot), chỉ để hiển thị.

Pi không tự đánh biển số hay giữ danh sách riêng: trang Phiên đỗ trên web là nguồn duy nhất.
Backend đánh biển demo (11111, 22222…) khi xe vào và chọn xe số lớn nhất khi xe ra; danh sách chỉ đổi
sau khi quản trị bấm Cho vào / Cho ra.
"""
import threading


class LotView:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"in_lot": [], "pending_entry": [], "pending_exit": [], "occurred_at": None}

    def update(self, msg):
        if msg.get("message_type") != "lot_state":
            return
        with self.lock:
            self.state = {k: msg.get(k) or ([] if k != "occurred_at" else None) for k in self.state}

    def snapshot(self):
        with self.lock:
            return {k: (list(v) if isinstance(v, list) else v) for k, v in self.state.items()}

    def summary(self):
        s = self.snapshot()
        parts = [f"Trong bai: {', '.join(s['in_lot']) or '-'}"]
        if s["pending_entry"]:
            parts.append(f"Cho vao: {', '.join(s['pending_entry'])}")
        if s["pending_exit"]:
            parts.append(f"Cho ra: {', '.join(s['pending_exit'])}")
        return " | ".join(parts)
