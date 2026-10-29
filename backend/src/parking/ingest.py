"""Lambda nhận message thiết bị qua IoT Rule (docs/mqtt-contract.md, docs/use-cases.md).

Mỗi sự kiện xe ghi dấu `event_id` trong cùng transaction với tác dụng của nó, nên replay QoS 1 hay
Lambda retry không tạo phiên/lệnh thứ hai (SIM-10). Lệnh MQTT chỉ phát sau khi transaction thành công;
phát lỗi thì ném ra, Lambda retry gặp DUPLICATE nên không mở cần lần hai.
Message sai schema bị bỏ và ghi log (không retry); lỗi hạ tầng ném ra để Lambda retry.
"""
from datetime import datetime

from .app import App, get_app
from .contract import SLOTS, InvalidMessage, display_command, parse_inbound
from .flows import (base_session, identity_fields, mark_parked, marker_op, publish, put_session_op, request_exit,
                    reserve_slot)
from .ids import new_ulid
from .layout import SLOT_IDS, source_of
from .log import log
from .plates import normalize_plate
from .store import ConditionFailed, TransactionCancelled, op_check, op_update, set_clause
from .timeutil import iso

VALID_LANES = {("ENTRY", "GREEN"), ("EXIT", "RED")}


def handler(event, _context):
    return process(get_app(), event)


def process(app: App, message) -> str:
    """Trả kết quả ngắn (không chứa biển số) để log và test."""
    now = app.clock()
    try:
        msg = parse_inbound(message, app.cfg.site_id)
    except InvalidMessage as e:
        topic = message.get("mqtt_topic") if isinstance(message, dict) else None
        log("mqtt_rejected", topic=topic, reason=str(e))
        return f"INVALID:{e}"
    outcome = HANDLERS[msg["message_type"]](app, msg, now)
    log("mqtt_processed", message_type=msg["message_type"], event_id=msg["event_id"], outcome=outcome)
    return outcome


# ---------- Xe vào/ra ----------

def on_vehicle_detected(app: App, msg: dict, now: datetime) -> str:
    if app.db.get(app.cfg.tables.processed, {"message_id": msg["event_id"]}):
        return "DUPLICATE"
    plate = normalize_plate(msg["plate_text"])
    reason = _review_reason(app, msg, plate, now)
    if reason:
        return _manual_review(app, msg, plate, reason, now)
    return _entry(app, msg, plate, now) if msg["lane_id"] == "ENTRY" else _exit(app, msg, plate, now)


def _review_reason(app: App, msg: dict, plate: str | None, now: datetime) -> str | None:
    """Mọi trường hợp không chắc chắn chuyển quản trị, không mở cần tự động (UC-07)."""
    cfg = app.cfg
    if (msg["lane_id"], msg["card_color"]) not in VALID_LANES:
        return "WRONG_LANE"
    age = (now - msg["occurred_at_dt"]).total_seconds()
    if age > cfg.event_max_age_s or age < -cfg.clock_skew_s:
        return "STALE_EVENT"  # sự kiện đến trễ (Pi mất mạng rồi gửi lại) không được mở cần
    if plate is None:
        return "UNREADABLE_PLATE"
    if msg["plate_confidence"] < cfg.plate_confidence_threshold:
        return "LOW_CONFIDENCE"
    return None


def _entry(app: App, msg: dict, plate: str, now: datetime) -> str:
    result = reserve_slot(app, marker_op(app, msg, now), new_ulid(now), plate, msg["plate_confidence"],
                          msg["event_id"], now)
    if result.outcome == "RESERVED":
        publish(app, result.commands)
        return f"RESERVED:{result.slot_id}"
    if result.outcome == "LEAD_FAILED":
        return "DUPLICATE"
    if result.outcome == "LOT_FULL":
        return _lot_full(app, msg, now)
    reason = "PLATE_ALREADY_ACTIVE" if result.outcome == "PLATE_ACTIVE" else result.outcome
    return _manual_review(app, msg, plate, reason, now, result.active_session_id)


def _lot_full(app: App, msg: dict, now: datetime) -> str:
    try:
        app.db.transact([marker_op(app, msg, now)])
    except TransactionCancelled as e:
        if e.failed(0):
            return "DUPLICATE"
        raise
    publish(app, [display_command(app.cfg.site_id, "LOT_FULL", ["BAI DA DAY", "Vui long quay lai", "sau it phut"],
                                  now, app.cfg.display_command_ttl_s)])
    return "LOT_FULL"


def _exit(app: App, msg: dict, plate: str, now: datetime) -> str:
    """Khóa phí lúc xe yêu cầu ra (UC-06). Mở cần ra là thao tác quản trị."""
    t = app.cfg.tables
    active = app.db.get(t.active_plates, {"plate_normalized": plate})
    session = active and app.db.get(t.sessions, {"session_id": active["session_id"]})
    if not session:
        return _manual_review(app, msg, plate, "NO_ACTIVE_SESSION", now)
    if session["state"] != "PARKED":
        return _manual_review(app, msg, plate, "SESSION_NOT_PARKED", now, session["session_id"])
    result = request_exit(app, marker_op(app, msg, now), session, now, ("PARKED",), now)
    if result.outcome == "LEAD_FAILED":
        return "DUPLICATE"
    if result.outcome == "NOT_PARKED":
        return _manual_review(app, msg, plate, "SESSION_NOT_PARKED", now, session["session_id"])
    publish(app, result.commands)
    return f"{result.state}:{result.fee_vnd}"


def _manual_review(app: App, msg: dict, plate: str | None, reason: str, now: datetime,
                   related_session_id: str | None = None) -> str:
    session = {
        **base_session(app, new_ulid(now), now),
        "state": "MANUAL_REVIEW",
        "review_reason": reason,
        "lane_id": msg["lane_id"],
        "card_color": msg["card_color"],
        "plate_normalized": plate,
        "plate_text": msg["plate_text"],
        "plate_confidence": msg["plate_confidence"],
        "related_session_id": related_session_id,
        "event_id": msg["event_id"],
        **identity_fields(app, now),
    }
    try:
        app.db.transact([marker_op(app, msg, now), put_session_op(app, session)])
    except TransactionCancelled as e:
        if e.failed(0):
            return "DUPLICATE"
        raise
    lane = "Cong vao" if msg["lane_id"] == "ENTRY" else "Cong ra"
    publish(app, [display_command(app.cfg.site_id, "ERROR", ["CHO NHAN VIEN", lane, "Vui long doi"],
                                  now, app.cfg.display_command_ttl_s)])
    return f"MANUAL_REVIEW:{reason}"


# ---------- Ô đỗ ----------

SNAPSHOT_IS_OLDER = "attribute_not_exists(snapshot_seq) OR snapshot_boot_id <> :boot OR snapshot_seq < :seq"
SLOT_IS_OLDER = "attribute_not_exists(src_seq) OR src_boot_id <> :boot OR src_seq < :seq"


def on_slot_changed(app: App, msg: dict, now: datetime) -> str:
    # Snapshot không ghi lại ô không đổi, nên phải so cả với seq của snapshot đã nhận: nếu không, một
    # slot_changed đến trễ có thể đổi ô đang có xe thành trống và cho xe khác vào.
    return _apply_slot(app, msg, msg["slot_id"], msg["occupied"], now, check_snapshot=True)


def on_slots_snapshot(app: App, msg: dict, now: datetime) -> str:
    """Ghi các ô trước, đánh dấu snapshot đã nhận sau cùng: lỗi giữa chừng thì Lambda retry làm lại được,
    và ô không bị coi là "dữ liệu mới" khi chưa ghi xong."""
    t = app.cfg.tables
    board = app.db.get(t.devices, {"device_id": SLOTS})
    if board and board.get("snapshot_boot_id") == msg["boot_id"] and board.get("snapshot_seq", -1) >= msg["seq"]:
        return "STALE"
    current = {s["slot_id"]: s for s in app.db.batch_get(t.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
    # Chỉ ghi ô đổi trạng thái: snapshot 30 giây/lần, ghi cả 18 ô sẽ tốn WCU vô ích.
    changed = [s for s in msg["slots"] if current.get(s["slot_id"], {}).get("occupied") != s["occupied"]]
    for s in changed:
        _apply_slot(app, msg, s["slot_id"], s["occupied"], now)
    update, names, values = set_clause({
        "last_snapshot_at": iso(now),
        "last_seen_at": iso(now),
        "snapshot_boot_id": msg["boot_id"],
        "snapshot_seq": msg["seq"],
    })
    try:
        app.db.update(t.devices, {"device_id": SLOTS}, update, SNAPSHOT_IS_OLDER,
                      {**values, ":boot": msg["boot_id"], ":seq": msg["seq"]}, names)
    except ConditionFailed:
        return "STALE"  # snapshot mới hơn vừa được ghi
    return f"SNAPSHOT:{len(changed)}"


def _apply_slot(app: App, msg: dict, slot_id: str, occupied: bool, now: datetime, check_snapshot: bool = False) -> str:
    """Ghi tín hiệu hiện trường, bỏ message cũ hơn trong cùng boot_id. Không đụng `reserved_session_id`.

    Dù message đã được ghi ở lần chạy trước (Lambda retry), vẫn chuyển phiên sang PARKED nếu lần trước lỗi giữa chừng.
    """
    t = app.cfg.tables
    update, names, values = set_clause({
        "occupied": occupied,
        "source": source_of(slot_id),
        "src_boot_id": msg["boot_id"],
        "src_seq": msg["seq"],
        "updated_at": iso(now),
    })
    seq = {":boot": msg["boot_id"], ":seq": msg["seq"]}
    ops = [op_update(t.slots, {"slot_id": slot_id}, update, SLOT_IS_OLDER, {**values, **seq}, names)]
    if check_snapshot:
        ops.append(op_check(t.devices, {"device_id": SLOTS}, SNAPSHOT_IS_OLDER, seq))
    try:
        app.db.transact(ops)
        outcome = f"{'OCCUPIED' if occupied else 'FREE'}:{slot_id}"
    except TransactionCancelled as e:
        if not any(e.failed(i) for i in range(len(ops))):
            raise
        outcome = f"STALE:{slot_id}"
    slot = app.db.get(t.slots, {"slot_id": slot_id}) or {}
    if slot.get("occupied") and slot.get("reserved_session_id") and mark_parked(app, slot["reserved_session_id"], now):
        return f"PARKED:{slot_id}"
    return outcome


# ---------- Cổng, OLED, thiết bị ----------

def on_gate_telemetry(app: App, msg: dict, now: datetime) -> str:
    t = app.cfg.tables
    gate = msg["gate"].lower()
    update, names, values = set_clause({
        f"{gate}_gate_state": msg["state"],
        f"{gate}_gate_error": msg["error_code"],
        f"{gate}_gate_command_id": msg["command_id"],
        f"{gate}_gate_at": iso(now),
        "last_seen_at": iso(now),
    })
    app.db.update(t.devices, {"device_id": msg["device_id"]}, update, values=values, names=names)
    outcome = f"{msg['gate']}:{msg['state']}"
    record = msg["command_id"] and app.db.get(t.processed, {"message_id": f"cmd#{msg['command_id']}"})
    if not record:
        return outcome
    if msg["state"] == "OPEN" and record.get("to_state"):
        sources = {f":from{i}": s for i, s in enumerate(record["from_states"])}
        update, names, values = set_clause({
            "state": record["to_state"], f"{gate}_gate_opened_at": iso(now), "updated_at": iso(now)})
        try:
            app.db.update(t.sessions, {"session_id": record["session_id"]}, update,
                          f"#f0 IN ({', '.join(sources)})", {**values, **sources}, names)
            outcome += f" → {record['to_state']}"
        except ConditionFailed:
            pass  # ACK đến sau khi phiên đã sang trạng thái mới hơn
    elif msg["state"] == "ERROR":
        update, names, values = set_clause({"gate_error": msg["error_code"] or "UNKNOWN", "gate_error_at": iso(now)})
        app.db.update(t.sessions, {"session_id": record["session_id"]}, update, values=values, names=names)
    return outcome


def on_display_telemetry(app: App, msg: dict, now: datetime) -> str:
    update, names, values = set_clause({
        "display_state": msg["state"],
        "display_command_id": msg["command_id"],
        "display_at": iso(now),
        "last_seen_at": iso(now),
    })
    app.db.update(app.cfg.tables.devices, {"device_id": msg["device_id"]}, update, values=values, names=names)
    return f"DISPLAY:{msg['state']}"


def on_device_status(app: App, msg: dict, now: datetime) -> str:
    """Last Will OFFLINE không cập nhật `last_seen_at`; timeout 90 giây vẫn là nguồn quyết định."""
    fields = {"state": msg["state"], "firmware_version": msg["firmware_version"], "boot_id": msg["boot_id"],
              "status_at": iso(now)}
    if msg["state"] != "OFFLINE":
        fields["last_seen_at"] = iso(now)
    update, names, values = set_clause(fields)
    app.db.update(app.cfg.tables.devices, {"device_id": msg["device_id"]}, update, values=values, names=names)
    return msg["state"]


HANDLERS = {
    "vehicle_detected": on_vehicle_detected,
    "slot_changed": on_slot_changed,
    "slots_snapshot": on_slots_snapshot,
    "gate_telemetry": on_gate_telemetry,
    "display_telemetry": on_display_telemetry,
    "device_status": on_device_status,
}
