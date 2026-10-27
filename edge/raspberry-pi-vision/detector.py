"""Nhận màu thẻ theo ROI, OCR biển số và ổn định kết quả qua nhiều frame."""
import logging
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Biển số VN: 2 số tỉnh + seri 1–2 chữ (có thể kèm 1 số) + 4–5 số, ví dụ 51A-12345, 59X1-23456.
# Có dấu phân cách thì tin dấu; không có thì ưu tiên seri không kèm số (51A12345 → 51A-12345).
PLATE_SEPARATED_RE = re.compile(r"(\d{2})([A-Z]{1,2}\d?)[-\s]+(\d{3}\.?\d{2}|\d{4})(?!\d)")
PLATE_RE = re.compile(r"(\d{2})([A-Z]{1,2}\d??)(\d{4,5})(?!\d)")
UNMATCHED_CONFIDENCE_CAP = 0.5


def crop(frame, roi):
    """Cắt frame theo ROI tỉ lệ [x, y, w, h]."""
    h, w = frame.shape[:2]
    x, y, rw, rh = roi
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = int((x + rw) * w), int((y + rh) * h)
    return frame[y0:y1, x0:x1]


def roi_to_pixels(roi, width, height):
    x, y, rw, rh = roi
    return (int(x * width), int(y * height)), (int((x + rw) * width), int((y + rh) * height))


class CardDetector:
    def __init__(self, colors_cfg, min_ratio):
        self.colors = {
            name: [(np.array(lo, np.uint8), np.array(hi, np.uint8)) for lo, hi in c["ranges"]]
            for name, c in colors_cfg.items()
        }
        self.min_ratio = min_ratio

    def ratios(self, roi_img):
        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        result = {}
        for name, ranges in self.colors.items():
            mask = np.zeros(hsv.shape[:2], np.uint8)
            for lo, hi in ranges:
                mask |= cv2.inRange(hsv, lo, hi)
            result[name] = cv2.countNonZero(mask) / mask.size
        return result

    def detect(self, roi_img):
        """Trả (màu, tỉ lệ từng màu); màu là None nếu không màu nào vượt ngưỡng."""
        ratios = self.ratios(roi_img)
        color, ratio = max(ratios.items(), key=lambda kv: kv[1])
        return (color if ratio >= self.min_ratio else None), ratios


def normalize_plate(raw):
    upper = raw.upper()
    m = PLATE_SEPARATED_RE.search(upper) or PLATE_RE.search(re.sub(r"[^A-Z0-9]", "", upper))
    return f"{m[1]}{m[2]}-{m[3].replace('.', '')}" if m else None


@dataclass
class PlateReading:
    text: str | None
    confidence: float


class PlateReader:
    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            log.warning("Chưa cài rapidocr_onnxruntime; mọi lượt sẽ gửi plate_text=null")
            self.engine = None
            return
        self.engine = RapidOCR()

    def read(self, img):
        if self.engine is None or img.size == 0:
            return PlateReading(None, 0.0)
        if img.shape[0] < 96:
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        result, _ = self.engine(img)
        if not result:
            return PlateReading(None, 0.0)
        # Ghép các dòng chữ từ trên xuống, trái sang phải để đọc được cả biển hai dòng.
        boxes = sorted(result, key=lambda r: (round(r[0][0][1] / 20), r[0][0][0]))
        raw = "".join(text for _, text, _ in boxes)
        confidence = float(np.mean([float(score) for _, _, score in boxes]))
        plate = normalize_plate(raw)
        if plate:
            return PlateReading(plate, round(confidence, 3))
        cleaned = re.sub(r"[^A-Z0-9-]", "", raw.upper()) or None
        return PlateReading(cleaned, round(min(confidence, UNMATCHED_CONFIDENCE_CAP), 3))


@dataclass
class Detection:
    lane_id: str
    card_color: str
    plate_text: str | None
    plate_confidence: float


@dataclass
class LaneTracker:
    """Chốt một lượt xe khi cùng màu ổn định nhiều frame; chờ thẻ rời ROI mới nhận lượt mới."""

    lane_id: str
    stable_frames: int
    clear_frames: int
    ocr_attempts: int
    dedupe_window_s: float
    confidence_threshold: float
    color: str | None = None
    count: int = 0
    missing: int = 0
    done: bool = False
    readings: list = field(default_factory=list)
    last_emit: tuple | None = None  # (màu, biển số, thời điểm)

    @property
    def state(self):
        if self.done:
            return "DONE"
        if self.color and self.count >= self.stable_frames:
            return "READING"
        return "CONFIRMING" if self.color else "IDLE"

    def update(self, color):
        """Cập nhật màu của frame; trả True nếu frame này cần OCR."""
        if color is None:
            self.missing += 1
            if self.missing >= self.clear_frames:
                self.color, self.count, self.done, self.readings = None, 0, False, []
            return False
        self.missing = 0
        if self.done:
            return False
        if color != self.color:
            self.color, self.count, self.readings = color, 0, []
        self.count += 1
        return self.count >= self.stable_frames

    def add_reading(self, reading, now):
        """Ghi một kết quả OCR; trả Detection khi đủ lần đọc hoặc đã đủ tin cậy."""
        self.readings.append(reading)
        confident = reading.text is not None and reading.confidence >= self.confidence_threshold
        if not confident and len(self.readings) < self.ocr_attempts:
            return None
        best = max(self.readings, key=lambda r: (r.text is not None, r.confidence))
        self.done = True
        if self.last_emit:
            color, plate, at = self.last_emit
            if (color, plate) == (self.color, best.text) and now - at < self.dedupe_window_s:
                log.info("Bỏ sự kiện trùng ở làn %s trong %ss", self.lane_id, self.dedupe_window_s)
                return None
        self.last_emit = (self.color, best.text, now)
        return Detection(self.lane_id, self.color, best.text, best.confidence)
