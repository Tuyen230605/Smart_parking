"""Trạng thái suy ra lúc đọc thay vì lưu sẵn, nên không cần job chuyển ô sang UNKNOWN hay thiết bị sang OFFLINE.

- Ô: `occupied` là tín hiệu hiện trường từ slots-01; `reserved_session_id` là quyết định của backend.
- Toàn bộ ô là UNKNOWN khi slots-01 không gửi snapshot quá `device_timeout_s` (docs/mqtt-contract.md §4).
"""
from datetime import datetime, timedelta

from .contract import DEVICES, SLOTS
from .layout import SLOT_IDS
from .pricing import DEFAULT_PRICING
from .timeutil import iso

# Phiên vào còn được xem QR/lộ trình.
CLAIM_STATES = ("RESERVED", "ENTRY_GATE_OPEN", "PARKED")


def cutoff(now: datetime, seconds: int) -> str:
    return iso(now - timedelta(seconds=seconds))


def board_fresh(board: dict | None, now: datetime, timeout_s: int) -> bool:
    at = (board or {}).get("last_snapshot_at")
    return bool(at) and at >= cutoff(now, timeout_s)


def device_online(item: dict | None, now: datetime, timeout_s: int) -> bool:
    if not item or item.get("state") == "OFFLINE":
        return False
    at = item.get("last_seen_at")
    return bool(at) and at >= cutoff(now, timeout_s)


def offline_devices(devices: dict[str, dict], now: datetime, timeout_s: int) -> list[str]:
    return [d for d in DEVICES if not device_online(devices.get(d), now, timeout_s)]


def slot_status(item: dict | None, fresh: bool) -> str:
    if item and item.get("out_of_service"):
        return "OUT_OF_SERVICE"
    if not item or not fresh or "occupied" not in item:
        return "UNKNOWN"
    if item["occupied"]:
        return "OCCUPIED"
    if item.get("reserved_session_id"):
        return "RESERVED"
    return "AVAILABLE"


def load_slots(app) -> tuple[dict[str, dict], dict | None]:
    """Trả (ô theo ID, bản ghi thiết bị slots-01)."""
    t = app.cfg.tables
    slots = {s["slot_id"]: s for s in app.db.batch_get(t.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
    return slots, app.db.get(t.devices, {"device_id": SLOTS})


def load_devices(app) -> dict[str, dict]:
    items = app.db.batch_get(app.cfg.tables.devices, [{"device_id": d} for d in DEVICES])
    return {d["device_id"]: d for d in items}


def load_pricing(app) -> dict:
    item = app.db.get(app.cfg.tables.pricing, {"pricing_id": "current"}, consistent=False)
    return item["rules"] if item else dict(DEFAULT_PRICING)
