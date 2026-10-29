"""Chuẩn hóa biển số VN; cùng quy tắc với edge/raspberry-pi-vision/detector.py."""
import re

# 2 số tỉnh + seri 1–2 chữ (có thể kèm 1 số) + 4–5 số, ví dụ 51A-12345, 59X1-23456.
PLATE_SEPARATED_RE = re.compile(r"(\d{2})([A-Z]{1,2}\d?)[-\s]+(\d{3}\.?\d{2}|\d{4})(?!\d)")
PLATE_RE = re.compile(r"(\d{2})([A-Z]{1,2}\d??)(\d{4,5})(?!\d)")


def normalize_plate(raw: str | None) -> str | None:
    """Trả dạng 51A-12345, hoặc None nếu không khớp mẫu biển số."""
    if not raw:
        return None
    upper = raw.upper()
    m = PLATE_SEPARATED_RE.fullmatch(upper.strip()) or PLATE_RE.fullmatch(re.sub(r"[^A-Z0-9]", "", upper))
    return f"{m[1]}{m[2]}-{m[3].replace('.', '')}" if m else None
