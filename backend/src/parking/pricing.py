"""Bảng giá demo (docs/architecture.md §7). Phiên chép bảng giá lúc check-in nên đổi giá không ảnh hưởng xe đang đỗ."""
import math
from datetime import datetime

DEFAULT_PRICING = {
    "version": 1,
    "free_minutes": 15,
    "first_block_minutes": 60,
    "first_block_vnd": 10_000,
    "extra_hour_vnd": 5_000,
}


def compute_fee(pricing: dict, checkin_at: datetime, charge_end_at: datetime) -> int:
    """Dưới 15 phút: 0 ₫; đến hết 60 phút: 10.000 ₫; mỗi giờ tiếp theo bắt đầu: +5.000 ₫."""
    seconds = max(0.0, (charge_end_at - checkin_at).total_seconds())
    if seconds < pricing["free_minutes"] * 60:
        return 0
    first_block_s = pricing["first_block_minutes"] * 60
    if seconds <= first_block_s:
        return pricing["first_block_vnd"]
    extra_hours = math.ceil((seconds - first_block_s) / 3600)
    return pricing["first_block_vnd"] + extra_hours * pricing["extra_hour_vnd"]
