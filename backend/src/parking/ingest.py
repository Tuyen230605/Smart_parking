"""Lambda nhận message thiết bị qua IoT Rule (docs/mqtt-contract.md, docs/use-cases.md).

Mỗi sự kiện xe ghi dấu `event_id` trong cùng transaction với tác dụng của nó, nên replay QoS 1 hay
Lambda retry không tạo phiên/lệnh thứ hai (SIM-10). Lệnh MQTT chỉ phát sau khi transaction thành công.
Message sai schema bị bỏ và ghi log (không retry); lỗi hạ tầng ném ra để Lambda retry.
"""
from datetime import datetime, timedelta

from .app import App, get_app
from .claims import new_nonce
from .contract import SLOTS, InvalidMessage, display_command, gate_command, parse_inbound
from .ids import new_session_ref, new_ulid
from .layout import SLOT_IDS, oled_route_lines, source_of
from .log import log
from .plates import normalize_plate
from .pricing import compute_fee
from .state import board_fresh, cutoff, load_pricing
from .store import ConditionFailed, TransactionCancelled, op_check, op_put, op_update, set_clause
from .timeutil import epoch, from_epoch, iso, parse_iso

VALID_LANES = {("ENTRY", "GREEN"), ("EXIT", "RED")}


class PublishFailed(Exception):
    pass


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
    t = app.cfg.tables
    active = app.db.get(t.active_plates, {"plate_normalized": plate})
    if active:
        return _manual_review(app, msg, plate, "PLATE_ALREADY_ACTIVE", now, active["session_id"])
    board = app.db.get(t.devices, {"device_id": SLOTS})
    if not board_fresh(board, now, app.cfg.device_timeout_s):
        return _manual_review(app, msg, plate, "SLOTS_UNKNOWN", now)
    slots = {s["slot_id"]: s for s in app.db.batch_get(t.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
    pricing = load_pricing(app)
    for slot_id in (sid for sid in SLOT_IDS if _assignable(slots.get(sid))):
        ops, commands = _reservation(app, msg, plate, slot_id, pricing, now)
        try:
            app.db.transact(ops)
        except TransactionCancelled as e:
            if e.failed(0):
                return "DUPLICATE"
            if e.failed(1):
                active = app.db.get(t.active_plates, {"plate_normalized": plate}) or {}
                return _manual_review(app, msg, plate, "PLATE_ALREADY_ACTIVE", now, active.get("session_id"))
            if e.failed(2):
                return _manual_review(app, msg, plate, "SLOTS_UNKNOWN", now)
            if e.failed(3):
                continue  # ô vừa bị lượt khác giữ hoặc vừa có xe: thử ô kế tiếp (SIM-09)
            raise
        _publish(app, commands)
        return f"RESERVED:{slot_id}"
    return _lot_full(app, msg, now)


def _assignable(slot: dict | None) -> bool:
    return bool(slot) and slot.get("occupied") is False and not slot.get("reserved_session_id") \
        and not slot.get("out_of_service")


def _reservation(app: App, msg: dict, plate: str, slot_id: str, pricing: dict, now: datetime):
    """Một transaction: dấu sự kiện, khóa biển số, ô còn dữ liệu mới, giữ ô, tạo phiên, ghi lệnh mở cần."""
    cfg, t = app.cfg, app.cfg.tables
    session_id = new_ulid(now)
    gate_topic, gate_cmd = gate_command(cfg.site_id, "ENTRY", "OPEN", session_id, now, cfg.gate_command_ttl_s)
    claim_expires = from_epoch(epoch(now) + cfg.claim_ttl_s)
    session = {
        "session_id": session_id,
        "session_ref": new_session_ref(),
        "state": "RESERVED",
        "lane_id": "ENTRY",
        "slot_id": slot_id,
        "plate_normalized": plate,
        "plate_confidence": msg["plate_confidence"],
        "event_id": msg["event_id"],
        "checkin_at": iso(now),
        "created_at": iso(now),
        "updated_at": iso(now),
        "claim_nonce": new_nonce(),
        "claim_expires_at": iso(claim_expires),
        "claim_pk": cfg.site_id,
        "pricing": pricing,
        "entry_command_id": gate_cmd["command_id"],
        **_identity(app, now),
    }
    ops = [
        _marker(app, msg, now),
        op_put(t.active_plates, {"plate_normalized": plate, "session_id": session_id, "created_at": iso(now)},
               "attribute_not_exists(plate_normalized)"),
        op_check(t.devices, {"device_id": SLOTS}, "last_snapshot_at >= :cutoff",
                 {":cutoff": cutoff(now, cfg.device_timeout_s)}),
        op_update(t.slots, {"slot_id": slot_id},
                  "SET reserved_session_id = :sid, reserved_at = :now, updated_at = :now",
                  "occupied = :false AND attribute_not_exists(reserved_session_id)"
                  " AND (attribute_not_exists(out_of_service) OR out_of_service = :false)",
                  {":sid": session_id, ":now": iso(now), ":false": False}),
        _put_session(app, session),
        _command_record(app, gate_cmd, session_id, "ENTRY", ["RESERVED"], "ENTRY_GATE_OPEN", now),
    ]
    commands = [
        (gate_topic, gate_cmd),
        display_command(cfg.site_id, "ENTRY_ROUTE", oled_route_lines(slot_id), now, cfg.display_command_ttl_s),
    ]
    return ops, commands


def _lot_full(app: App, msg: dict, now: datetime) -> str:
    try:
        app.db.transact([_marker(app, msg, now)])
    except TransactionCancelled as e:
        if e.failed(0):
            return "DUPLICATE"
        raise
    _publish(app, [display_command(app.cfg.site_id, "LOT_FULL", ["BAI DA DAY", "Vui long quay lai", "sau it phut"],
                                   now, app.cfg.display_command_ttl_s)])
    return "LOT_FULL"


def _exit(app: App, msg: dict, plate: str, now: datetime) -> str:
    """Khóa `charge_end_at` và số tiền lúc xe yêu cầu ra (UC-06). Mở cần ra là thao tác quản trị."""
    cfg, t = app.cfg, app.cfg.tables
    active = app.db.get(t.active_plates, {"plate_normalized": plate})
    session = active and app.db.get(t.sessions, {"session_id": active["session_id"]})
    if not session:
        return _manual_review(app, msg, plate, "NO_ACTIVE_SESSION", now)
    if session["state"] != "PARKED":
        return _manual_review(app, msg, plate, "SESSION_NOT_PARKED", now, session["session_id"])
    fee = compute_fee(session["pricing"], parse_iso(session["checkin_at"]), now)
    state = "EXIT_REQUESTED" if fee == 0 else "PAYMENT_PENDING"
    update, names, values = set_clause({
        "state": state,
        "charge_end_at": iso(now),
        "fee_vnd": fee,
        "payment_status": "NO_CHARGE" if fee == 0 else "PENDING",
        "exit_event_id": msg["event_id"],
        "updated_at": iso(now),
    })
    try:
        app.db.transact([
            _marker(app, msg, now),
            op_update(t.sessions, {"session_id": session["session_id"]}, update, "#f0 = :parked",
                      {**values, ":parked": "PARKED"}, names),
        ])
    except TransactionCancelled as e:
        if e.failed(0):
            return "DUPLICATE"
        if e.failed(1):
            return _manual_review(app, msg, plate, "SESSION_NOT_PARKED", now, session["session_id"])
        raise
    lines = ["RA - MIEN PHI", "Phi: 0 VND", "Cho nhan vien"] if fee == 0 \
        else ["RA - PHI GUI XE", f"Phi: {fee} VND", "Thanh toan tai cong"]
    _publish(app, [display_command(cfg.site_id, "EXIT_FEE", lines, now, cfg.display_command_ttl_s)])
    return f"{state}:{fee}"


def _manual_review(app: App, msg: dict, plate: str | None, reason: str, now: datetime,
                   related_session_id: str | None = None) -> str:
    session = {
        "session_id": new_ulid(now),
        "session_ref": new_session_ref(),
        "state": "MANUAL_REVIEW",
        "review_reason": reason,
        "lane_id": msg["lane_id"],
        "card_color": msg["card_color"],
        "plate_normalized": plate,
        "plate_text": msg["plate_text"],
        "plate_confidence": msg["plate_confidence"],
        "related_session_id": related_session_id,
        "event_id": msg["event_id"],
        "created_at": iso(now),
        "updated_at": iso(now),
        **_identity(app, now),
    }
    try:
        app.db.transact([_marker(app, msg, now), _put_session(app, session)])
    except TransactionCancelled as e:
        if e.failed(0):
            return "DUPLICATE"
        raise
    lane = "Cong vao" if msg["lane_id"] == "ENTRY" else "Cong ra"
    _publish(app, [display_command(app.cfg.site_id, "ERROR", ["CHO NHAN VIEN", lane, "Vui long doi"],
                                   now, app.cfg.display_command_ttl_s)])
    return f"MANUAL_REVIEW:{reason}"


# ---------- Ô đỗ ----------

def on_slot_changed(app: App, msg: dict, now: datetime) -> str:
    return _apply_slot(app, msg, msg["slot_id"], msg["occupied"], now)


def on_slots_snapshot(app: App, msg: dict, now: datetime) -> str:
    t = app.cfg.tables
    update, names, values = set_clause({
        "last_snapshot_at": iso(now),
        "last_seen_at": iso(now),
        "snapshot_boot_id": msg["boot_id"],
        "snapshot_seq": msg["seq"],
    })
    try:
        app.db.update(t.devices, {"device_id": SLOTS}, update,
                      "attribute_not_exists(snapshot_seq) OR snapshot_boot_id <> :boot OR snapshot_seq < :seq",
                      {**values, ":boot": msg["boot_id"], ":seq": msg["seq"]}, names)
    except ConditionFailed:
        return "STALE"
    current = {s["slot_id"]: s for s in app.db.batch_get(t.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
    # Chỉ ghi ô đổi trạng thái: snapshot 30 giây/lần, ghi cả 18 ô sẽ tốn WCU vô ích.
    changed = [s for s in msg["slots"] if current.get(s["slot_id"], {}).get("occupied") != s["occupied"]]
    for s in changed:
        _apply_slot(app, msg, s["slot_id"], s["occupied"], now)
    return f"SNAPSHOT:{len(changed)}"


def _apply_slot(app: App, msg: dict, slot_id: str, occupied: bool, now: datetime) -> str:
    """Ghi tín hiệu hiện trường; bỏ message cũ hơn trong cùng boot_id. Không đụng `reserved_session_id`."""
    t = app.cfg.tables
    update, names, values = set_clause({
        "occupied": occupied,
        "source": source_of(slot_id),
        "src_boot_id": msg["boot_id"],
        "src_seq": msg["seq"],
        "updated_at": iso(now),
    })
    try:
        slot = app.db.update(t.slots, {"slot_id": slot_id}, update,
                             "attribute_not_exists(src_seq) OR src_boot_id <> :boot OR src_seq < :seq",
                             {**values, ":boot": msg["boot_id"], ":seq": msg["seq"]}, names, return_new=True)
    except ConditionFailed:
        return f"STALE:{slot_id}"
    session_id = slot.get("reserved_session_id")
    if occupied and session_id:
        update, names, values = set_clause({"state": "PARKED", "parked_at": iso(now), "updated_at": iso(now)})
        try:
            app.db.update(t.sessions, {"session_id": session_id}, update, "#f0 IN (:reserved, :gate_open)",
                          {**values, ":reserved": "RESERVED", ":gate_open": "ENTRY_GATE_OPEN"}, names)
            return f"PARKED:{slot_id}"
        except ConditionFailed:
            pass
    return f"{'OCCUPIED' if occupied else 'FREE'}:{slot_id}"


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
            pass  # ACK đến sau khi xe đã vào ô: giữ nguyên trạng thái mới hơn
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


# ---------- Tiện ích ----------

def _identity(app: App, now: datetime) -> dict:
    """Hạn dữ liệu định danh: API ngừng trả ở mốc 10 ngày, purge xóa sớm hơn 1 giờ (docs/aws-deployment.md §6)."""
    expires = now + timedelta(seconds=app.cfg.identity_retention_s)
    return {
        "plate_collected_at": iso(now),
        "identity_expires_at": iso(expires),
        "purge_due_at": iso(expires - timedelta(seconds=app.cfg.purge_lead_s)),
        "pii_pk": app.cfg.site_id,
    }


def _marker(app: App, msg: dict, now: datetime) -> dict:
    return op_put(app.cfg.tables.processed, {
        "message_id": msg["event_id"],
        "kind": msg["message_type"],
        "processed_at": iso(now),
        "ttl": epoch(now) + app.cfg.processed_ttl_s,
    }, "attribute_not_exists(message_id)")


def _put_session(app: App, session: dict) -> dict:
    return op_put(app.cfg.tables.sessions, session, "attribute_not_exists(session_id)")


def _command_record(app: App, cmd: dict, session_id: str, gate: str, from_states: list[str], to_state: str,
                    now: datetime) -> dict:
    """Lưu command_id → phiên để ACK cổng chuyển đúng phiên sang trạng thái tiếp theo."""
    return op_put(app.cfg.tables.processed, {
        "message_id": f"cmd#{cmd['command_id']}",
        "kind": "gate_command",
        "session_id": session_id,
        "gate": gate,
        "from_states": from_states,
        "to_state": to_state,
        "issued_at": iso(now),
        "ttl": epoch(now) + app.cfg.processed_ttl_s,
    }, "attribute_not_exists(message_id)")


def _publish(app: App, commands: list[tuple[str, dict]]):
    """Phát hết các lệnh rồi mới báo lỗi. Lambda retry sẽ gặp DUPLICATE nên không mở cần hai lần."""
    failed = []
    for topic, payload in commands:
        try:
            app.publisher.publish(topic, payload)
        except Exception as e:
            log("publish_failed", topic=topic, command_id=payload.get("command_id"), error=type(e).__name__)
            failed.append(topic)
    if failed:
        raise PublishFailed(failed)
