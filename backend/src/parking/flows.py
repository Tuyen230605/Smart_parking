"""Thao tác nghiệp vụ dùng chung cho ingest (sự kiện thiết bị) và API quản trị.

Mỗi thao tác nhận một `lead_op` đứng đầu transaction: dấu `event_id` khi đến từ thiết bị, hoặc
cập nhật phiên MANUAL_REVIEW khi quản trị xử lý. Op này thất bại nghĩa là việc đã làm rồi.
Hàm trả về lệnh MQTT để caller tự phát sau khi transaction thành công.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .claims import new_nonce, sign_claim
from .contract import SLOTS, display_command, gate_command
from .ids import new_session_ref
from .layout import SLOT_IDS, oled_route_lines, route_steps
from .log import log
from .pricing import compute_fee
from .state import board_fresh, cutoff, load_pricing
from .store import ConditionFailed, TransactionCancelled, op_check, op_put, op_update, set_clause
from .timeutil import epoch, from_epoch, iso, parse_iso

PAID_STATUSES = ("NO_CHARGE", "PAID_CASH", "WAIVED")


class PublishFailed(Exception):
    pass


@dataclass
class Reservation:
    outcome: str  # RESERVED | LEAD_FAILED | PLATE_ACTIVE | SLOTS_UNKNOWN | LOT_FULL
    slot_id: str | None = None
    active_session_id: str | None = None
    commands: list = field(default_factory=list)


@dataclass
class ExitRequest:
    outcome: str  # REQUESTED | LEAD_FAILED | NOT_PARKED
    state: str | None = None
    fee_vnd: int | None = None
    commands: list = field(default_factory=list)


def reserve_slot(app, lead_op: dict, session_id: str, plate: str, confidence: float | None,
                 source_event_id: str | None, now: datetime, extra: dict | None = None) -> Reservation:
    """Giữ ô trống ưu tiên nhất và tạo phiên RESERVED; ô vừa bị lượt khác giữ thì thử ô kế tiếp (SIM-09).

    `extra` thêm thuộc tính vào phiên mới, ví dụ phiên MANUAL_REVIEW mà quản trị đã xử lý.
    """
    t = app.cfg.tables
    active = app.db.get(t.active_plates, {"plate_normalized": plate})
    if active:
        return Reservation("PLATE_ACTIVE", active_session_id=active["session_id"])
    if not board_fresh(app.db.get(t.devices, {"device_id": SLOTS}), now, app.cfg.device_timeout_s):
        return Reservation("SLOTS_UNKNOWN")
    slots = {s["slot_id"]: s for s in app.db.batch_get(t.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
    pricing = load_pricing(app)
    for slot_id in (sid for sid in SLOT_IDS if _assignable(slots.get(sid))):
        ops, commands = _reservation_ops(app, lead_op, session_id, plate, confidence, source_event_id, slot_id,
                                         pricing, now, extra or {})
        try:
            app.db.transact(ops)
        except TransactionCancelled as e:
            if e.failed(0):
                return Reservation("LEAD_FAILED")
            if e.failed(1):
                active = app.db.get(t.active_plates, {"plate_normalized": plate}) or {}
                return Reservation("PLATE_ACTIVE", active_session_id=active.get("session_id"))
            if e.failed(2):
                return Reservation("SLOTS_UNKNOWN")
            if e.failed(3):
                continue
            raise
        return Reservation("RESERVED", slot_id=slot_id, commands=commands)
    return Reservation("LOT_FULL")


def _assignable(slot: dict | None) -> bool:
    return bool(slot) and slot.get("occupied") is False and not slot.get("reserved_session_id") \
        and not slot.get("out_of_service")


def _reservation_ops(app, lead_op, session_id, plate, confidence, source_event_id, slot_id, pricing, now, extra):
    """Thứ tự op cố định để đọc lý do hủy: 0 lead, 1 biển số, 2 ô còn mới, 3 giữ ô, 4 phiên, 5 lệnh."""
    cfg, t = app.cfg, app.cfg.tables
    gate_topic, gate_cmd = gate_command(cfg.site_id, "ENTRY", "OPEN", session_id, now, cfg.gate_command_ttl_s)
    session = {
        **extra,
        **base_session(app, session_id, now),
        "state": "RESERVED",
        "lane_id": "ENTRY",
        "slot_id": slot_id,
        "plate_normalized": plate,
        "plate_confidence": confidence,
        "event_id": source_event_id,
        "checkin_at": iso(now),
        "claim_nonce": new_nonce(),
        "claim_expires_at": iso(from_epoch(epoch(now) + cfg.claim_ttl_s)),
        "claim_pk": cfg.site_id,
        "pricing": pricing,
        "entry_command_id": gate_cmd["command_id"],
        **identity_fields(app, now),
    }
    ops = [
        lead_op,
        op_put(t.active_plates, {"plate_normalized": plate, "session_id": session_id, "created_at": iso(now)},
               "attribute_not_exists(plate_normalized)"),
        op_check(t.devices, {"device_id": SLOTS}, "last_snapshot_at >= :cutoff",
                 {":cutoff": cutoff(now, cfg.device_timeout_s)}),
        op_update(t.slots, {"slot_id": slot_id},
                  "SET reserved_session_id = :sid, reserved_at = :now, updated_at = :now",
                  "occupied = :false AND attribute_not_exists(reserved_session_id)"
                  " AND (attribute_not_exists(out_of_service) OR out_of_service = :false)",
                  {":sid": session_id, ":now": iso(now), ":false": False}),
        put_session_op(app, session),
        command_record_op(app, gate_cmd, session_id, ["RESERVED"], "ENTRY_GATE_OPEN", now),
    ]
    commands = [
        (gate_topic, gate_cmd),
        display_command(cfg.site_id, "ENTRY_ROUTE", oled_route_lines(slot_id), now, cfg.display_command_ttl_s),
    ]
    return ops, commands


def mark_parked(app, session_id: str, now: datetime) -> bool:
    """Ô được gán đã báo có xe → PARKED. Gọi lại vô hại: chỉ chuyển từ RESERVED/ENTRY_GATE_OPEN."""
    update, names, values = set_clause({"state": "PARKED", "parked_at": iso(now), "updated_at": iso(now)})
    try:
        app.db.update(app.cfg.tables.sessions, {"session_id": session_id}, update, "#f0 IN (:reserved, :gate_open)",
                      {**values, ":reserved": "RESERVED", ":gate_open": "ENTRY_GATE_OPEN"}, names)
        return True
    except ConditionFailed:
        return False


def request_exit(app, lead_op: dict, session: dict, charge_end_at: datetime, from_states: tuple[str, ...],
                 now: datetime) -> ExitRequest:
    """Khóa `charge_end_at` và phí (UC-06). 0 ₫ → EXIT_REQUESTED/NO_CHARGE, có phí → PAYMENT_PENDING/PENDING."""
    cfg = app.cfg
    fee = compute_fee(session["pricing"], parse_iso(session["checkin_at"]), charge_end_at)
    state = "EXIT_REQUESTED" if fee == 0 else "PAYMENT_PENDING"
    update, names, values = set_clause({
        "state": state,
        "charge_end_at": iso(charge_end_at),
        "fee_vnd": fee,
        "payment_status": "NO_CHARGE" if fee == 0 else "PENDING",
        "updated_at": iso(now),
    })
    allowed = {f":from{i}": s for i, s in enumerate(from_states)}
    try:
        app.db.transact([
            lead_op,
            op_update(cfg.tables.sessions, {"session_id": session["session_id"]}, update,
                      f"#f0 IN ({', '.join(allowed)})", {**values, **allowed}, names),
        ])
    except TransactionCancelled as e:
        if e.failed(0):
            return ExitRequest("LEAD_FAILED")
        if e.failed(1):
            return ExitRequest("NOT_PARKED")
        raise
    lines = ["RA - MIEN PHI", "Phi: 0 VND", "Cho nhan vien"] if fee == 0 \
        else ["RA - PHI GUI XE", f"Phi: {fee} VND", "Thanh toan tai cong"]
    commands = [display_command(cfg.site_id, "EXIT_FEE", lines, now, cfg.display_command_ttl_s)]
    return ExitRequest("REQUESTED", state, fee, commands)


def claim_summary(app, session: dict, keys: list[bytes]) -> dict:
    """Thông tin QR cho kiosk/quản trị. Token ký lại từ nonce và hạn đang lưu nên URL ổn định giữa các lần gọi."""
    token = sign_claim(keys, session["session_id"], session["claim_nonce"],
                       epoch(parse_iso(session["claim_expires_at"])))
    return {
        "session_ref": session["session_ref"],
        "slot_id": session["slot_id"],
        "route_steps": route_steps(session["slot_id"]),
        "claim_url": f"{app.cfg.web_base_url}/s/{token}",
        "claim_expires_at": session["claim_expires_at"],
        "created_at": session["created_at"],
    }


def base_session(app, session_id: str, now: datetime) -> dict:
    """`site_id` + `created_at` là khóa index `by_site` để quản trị xem mọi phiên theo thời gian."""
    return {
        "session_id": session_id,
        "session_ref": new_session_ref(),
        "site_id": app.cfg.site_id,
        "created_at": iso(now),
        "updated_at": iso(now),
    }


def identity_fields(app, now: datetime) -> dict:
    """Hạn dữ liệu định danh: API ngừng trả ở mốc 10 ngày, purge xóa sớm hơn 1 giờ (docs/aws-deployment.md §6)."""
    expires = now + timedelta(seconds=app.cfg.identity_retention_s)
    return {
        "plate_collected_at": iso(now),
        "identity_expires_at": iso(expires),
        "purge_due_at": iso(expires - timedelta(seconds=app.cfg.purge_lead_s)),
        "pii_pk": app.cfg.site_id,
    }


def marker_op(app, msg: dict, now: datetime) -> dict:
    return op_put(app.cfg.tables.processed, {
        "message_id": msg["event_id"],
        "kind": msg["message_type"],
        "processed_at": iso(now),
        "ttl": epoch(now) + app.cfg.processed_ttl_s,
    }, "attribute_not_exists(message_id)")


def put_session_op(app, session: dict) -> dict:
    return op_put(app.cfg.tables.sessions, session, "attribute_not_exists(session_id)")


def command_record_op(app, cmd: dict, session_id: str, from_states: list[str], to_state: str,
                      now: datetime) -> dict:
    """Lưu command_id → phiên để ACK `OPEN` chuyển đúng phiên sang trạng thái tiếp theo."""
    return op_put(app.cfg.tables.processed, {
        "message_id": f"cmd#{cmd['command_id']}",
        "kind": "gate_command",
        "session_id": session_id,
        "gate": cmd["gate"],
        "from_states": from_states,
        "to_state": to_state,
        "issued_at": iso(now),
        "ttl": epoch(now) + app.cfg.processed_ttl_s,
    }, "attribute_not_exists(message_id)")


def publish(app, commands: list[tuple[str, dict]]):
    """Phát hết các lệnh rồi mới báo lỗi, để một lệnh hỏng không chặn lệnh còn lại."""
    failed = []
    for topic, payload in commands:
        try:
            app.publisher.publish(topic, payload)
        except Exception as e:
            log("publish_failed", topic=topic, command_id=payload.get("command_id"), error=type(e).__name__)
            failed.append(topic)
    if failed:
        raise PublishFailed(failed)
