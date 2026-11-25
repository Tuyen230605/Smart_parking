"""Phát hiện "có xe" trong một làn bằng cách so ảnh với nền trống (không cần thẻ màu hay biển số).

Mỗi làn giữ một ảnh nền xám, thu nhỏ. Tỉ lệ điểm ảnh lệch khỏi nền vượt `min_ratio` trong
`stable_frames` frame liên tiếp → coi là có vật (tay/xe mô hình) và báo đúng MỘT lần. Vật phải rời làn
`clear_frames` frame mới nhận lượt tiếp theo. Nền tự cập nhật chậm khi làn trống (ánh sáng thay đổi),
và nếu vật nằm yên quá `absorb_after_s` giây thì nó được nhập vào nền để làn không kẹt mãi.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class PresenceConfig:
    diff_threshold: int = 30     # độ lệch xám (0–255) để coi một điểm ảnh là "khác nền"
    min_ratio: float = 0.08      # tỉ lệ điểm ảnh khác nền tối thiểu để coi là có vật
    stable_frames: int = 3       # số frame liên tiếp có vật trước khi báo
    clear_frames: int = 8        # số frame liên tiếp trống để nhận lượt mới
    cooldown_s: float = 3.0      # sau một lượt, chờ tối thiểu chừng này giây mới báo lượt mới
    absorb_after_s: float = 15.0  # vật nằm yên lâu hơn → nhập vào nền
    work_width: int = 160        # thu nhỏ ROI về bề rộng này trước khi so (nhanh, bớt nhiễu)
    background_alpha: float = 0.05  # tốc độ cập nhật nền khi làn trống


def prepare(roi_img, width):
    scale = width / roi_img.shape[1]
    small = cv2.resize(roi_img, (width, max(1, int(roi_img.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (5, 5), 0).astype(np.float32)


class LanePresence:
    def __init__(self, lane_id, cfg: PresenceConfig):
        self.lane_id = lane_id
        self.cfg = cfg
        self.background = None
        self.hits = 0          # số frame liên tiếp có vật
        self.misses = 0        # số frame liên tiếp trống
        self.armed = True      # True = sẵn sàng báo lượt mới
        self.present_since = None
        self.last_fire = -1e9
        self.ratio = 0.0

    @property
    def state(self):
        if not self.armed:
            return "DA BAO"
        return "THAY VAT" if self.hits else "TRONG"

    def reset_background(self):
        self.background = None

    def update(self, roi_img, now):
        """Đưa một frame ROI vào; trả True đúng một lần khi có vật mới đi vào làn."""
        cfg = self.cfg
        gray = prepare(roi_img, cfg.work_width)
        if self.background is None or self.background.shape != gray.shape:
            self.background = gray.copy()
            self.ratio = 0.0
            return False
        # Bù chênh sáng toàn ROI (camera tự chỉnh phơi sáng) trước khi so từng điểm ảnh.
        diff = np.abs((gray - gray.mean()) - (self.background - self.background.mean()))
        self.ratio = float(np.count_nonzero(diff > cfg.diff_threshold)) / diff.size
        present = self.ratio >= cfg.min_ratio

        if present:
            self.hits += 1
            self.misses = 0
            if self.present_since is None:
                self.present_since = now
            if now - self.present_since > cfg.absorb_after_s:
                # Vật đứng yên quá lâu (ví dụ đặt đồ vào làn) → coi là nền mới, không báo thêm.
                self.background = gray.copy()
                self.hits, self.present_since = 0, None
                return False
            if self.armed and self.hits >= cfg.stable_frames and now - self.last_fire >= cfg.cooldown_s:
                self.armed = False
                self.last_fire = now
                return True
            return False

        self.hits = 0
        self.present_since = None
        self.misses += 1
        if self.misses >= cfg.clear_frames:
            self.armed = True
        cv2.accumulateWeighted(gray, self.background, cfg.background_alpha)
        return False
