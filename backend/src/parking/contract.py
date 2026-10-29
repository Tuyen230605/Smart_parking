"""Kiểm tra message MQTT v1 từ thiết bị và tạo lệnh gửi xuống (docs/mqtt-contract.md).

IoT Rule thêm `mqtt_topic` vào payload. Policy IoT chỉ cho mỗi thiết bị publish topic của nó, nên
backend tin topic và yêu cầu `device_id` trong payload trùng với topic.
"""
import re
import uuid
from datetime import datetime, timedelta

from .ids import new_uuid
from .layout import SLOT_IDS, source_of
from .timeutil import iso, parse_iso

PI, GATE, SLOTS = "pi-01", "gate-01", "slots-01"
DEVICES = (PI, GATE, SLOTS)

# (loại topic, đuôi topic) → (thiết bị được publish, message_type hợp lệ)
INBOUND = {
    ("vision", "events"): ({PI}, {"vehicle_detected"}),
    ("slots", "state"): ({SLOTS}, {"slot_changed", "slots_snapshot"}),
    ("gates", "telemetry"): ({GATE}, {"gate_telemetry"}),
    ("displays", "telemetry"): ({GATE}, {"display_telemetry"}),
    ("devices", "status"): (set(DEVICES), {"device_status"}),
}
# Mục 2 của hợp đồng: sự kiện thiết bị có boot_id + seq. Ví dụ telemetry cổng/OLED chưa có hai trường này.
NEEDS_SEQUENCE = {"vehicle_detected", "slot_changed", "slots_snapshot", "device_status"}

GATES = ("ENTRY", "EXIT")
GATE_STATES = {"OPENING", "OPEN", "CLOSING", "CLOSED", "ERROR"}
GATE_ERRORS = {"COMMAND_EXPIRED", "DUPLICATE_COMMAND", "WRONG_TARGET", "MOTOR_TIMEOUT", "SCHEMA_UNSUPPORTED"}
DEVICE_STATES = {"ONLINE", "DEGRADED", "OFFLINE"}
SCREENS = {"ENTRY_ROUTE", "EXIT_FEE", "LOT_FULL", "ERROR", "IDLE"}
OLED_LINE_RE = re.compile(r"[\x20-\x7e]{0,20}")


class InvalidMessage(ValueError):
    pass


def _require(ok: bool, reason: str):
    if not ok:
        raise InvalidMessage(reason)


def _is_int(value) -> bool:
    return type(value) is int


def _is_number(value) -> bool:
    return type(value) in (int, float)


def _is_uuid(value) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def parse_inbound(message, site_id: str) -> dict:
    """Trả bản sao message đã kiểm tra, thêm `occurred_at_dt`. Ném InvalidMessage nếu sai."""
    _require(isinstance(message, dict), "payload không phải object")
    parts = str(message.get("mqtt_topic", "")).split("/")
    _require(len(parts) == 6 and parts[:3] == ["parking", "v1", site_id], "topic lạ")
    kind, device, leaf = parts[3:]
    allowed = INBOUND.get((kind, leaf))
    _require(allowed is not None and device in allowed[0], "thiết bị không được publish topic này")
    _require(_is_int(message.get("schema_version")) and message["schema_version"] == 1, "schema_version không hỗ trợ")
    mtype = message.get("message_type")
    _require(mtype in allowed[1], "message_type không thuộc topic")
    _require(message.get("device_id") == device, "device_id khác topic")
    _require(_is_uuid(message.get("event_id")), "event_id không phải UUID")
    try:
        occurred = parse_iso(message.get("occurred_at"))
    except ValueError:
        raise InvalidMessage("occurred_at sai định dạng") from None
    if mtype in NEEDS_SEQUENCE:
        _require(_is_uuid(message.get("boot_id")), "boot_id không phải UUID")
        _require(_is_int(message.get("seq")) and message["seq"] >= 0, "seq không hợp lệ")
    msg = dict(message, occurred_at_dt=occurred)
    VALIDATORS[mtype](msg)
    return msg


def _vehicle_detected(m):
    _require(m.get("lane_id") in GATES, "lane_id")
    _require(m.get("card_color") in ("GREEN", "RED"), "card_color")
    plate = m.get("plate_text")
    _require(plate is None or (isinstance(plate, str) and 0 < len(plate) <= 20), "plate_text")
    conf = m.get("plate_confidence")
    _require(_is_number(conf) and 0 <= conf <= 1, "plate_confidence")


def _slot(entry: dict):
    _require(isinstance(entry, dict) and entry.get("slot_id") in SLOT_IDS, "slot_id")
    _require(type(entry.get("occupied")) is bool, "occupied")
    _require(entry.get("source") == source_of(entry["slot_id"]), "source không khớp bảng ánh xạ")


def _slot_changed(m):
    _slot(m)


def _slots_snapshot(m):
    slots = m.get("slots")
    _require(isinstance(slots, list) and len(slots) == len(SLOT_IDS), "snapshot phải có đủ 18 ô")
    for entry in slots:
        _slot(entry)
    _require({s["slot_id"] for s in slots} == set(SLOT_IDS), "snapshot trùng hoặc thiếu ô")


def _gate_telemetry(m):
    _require(m.get("command_id") is None or _is_uuid(m["command_id"]), "command_id")
    _require(m.get("gate") in GATES, "gate")
    _require(m.get("state") in GATE_STATES, "state")
    _require(m.get("error_code") is None or m["error_code"] in GATE_ERRORS, "error_code")


def _display_telemetry(m):
    _require(_is_uuid(m.get("command_id")), "command_id")
    _require(m.get("state") in ("SHOWN", "ERROR"), "state")


def _device_status(m):
    _require(m.get("state") in DEVICE_STATES, "state")
    fw = m.get("firmware_version")
    _require(isinstance(fw, str) and 0 < len(fw) <= 32, "firmware_version")


VALIDATORS = {
    "vehicle_detected": _vehicle_detected,
    "slot_changed": _slot_changed,
    "slots_snapshot": _slots_snapshot,
    "gate_telemetry": _gate_telemetry,
    "display_telemetry": _display_telemetry,
    "device_status": _device_status,
}


def gate_command(site_id: str, gate: str, action: str, session_id: str, now: datetime, ttl_s: int,
                 command_id: str | None = None) -> tuple[str, dict]:
    assert gate in GATES and action in ("OPEN", "CLOSE")
    return f"parking/v1/{site_id}/gates/{GATE}/commands", {
        "schema_version": 1,
        "message_type": "gate_command",
        "command_id": command_id or new_uuid(),
        "target_device_id": GATE,
        "gate": gate,
        "action": action,
        "session_id": session_id,
        "issued_at": iso(now),
        "expires_at": iso(now + timedelta(seconds=ttl_s)),
    }


def display_command(site_id: str, screen: str, lines: list[str], now: datetime, ttl_s: int) -> tuple[str, dict]:
    assert screen in SCREENS and len(lines) <= 3 and all(OLED_LINE_RE.fullmatch(line) for line in lines), lines
    return f"parking/v1/{site_id}/displays/{GATE}/commands", {
        "schema_version": 1,
        "message_type": "display_command",
        "command_id": new_uuid(),
        "target_device_id": GATE,
        "screen": screen,
        "lines": lines,
        "issued_at": iso(now),
        "expires_at": iso(now + timedelta(seconds=ttl_s)),
    }
