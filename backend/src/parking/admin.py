"""Endpoint quản trị (docs/api-contract.md §3). Mọi thay đổi cần nhóm ADMIN, Idempotency-Key và ghi audit.

Idempotency không cần bảng riêng: mỗi thao tác lưu key của nó ngay trên phiên (hoặc bảng giá) trong cùng
lần ghi có điều kiện. Gửi lại cùng key thì điều kiện sai, đọc lại thấy key khớp và trả trạng thái hiện tại.
Không lưu bản sao response, nên không giữ dữ liệu định danh ngoài phiên và không có trạng thái "đang xử lý".
Audit (`audit` trên phiên) ghi người làm, thời điểm, lý do; không chứa biển số hay email.
"""
import base64
import json
import re
from datetime import datetime

from .app import App
from .claims import new_nonce
from .contract import DEVICES, GATE, GATES, SLOTS, display_command, gate_command
from .flows import (PAID_STATUSES, PublishFailed, claim_summary, command_record_op, publish, request_exit,
                    reserve_slot)
from .ids import new_ulid
from .plates import normalize_plate
from .pricing import DEFAULT_PRICING
from .rest import ApiError, Request, idempotency_key, json_body, text_field
from .state import CLAIM_STATES, board_fresh, device_online
from .store import ConditionFailed, TransactionCancelled, op_delete, op_update, set_clause
from .timeutil import epoch, from_epoch, iso, parse_iso

SESSION_STATES = (
    "RESERVED", "ENTRY_GATE_OPEN", "PARKED", "EXIT_REQUESTED", "PAYMENT_PENDING", "EXIT_GATE_OPEN", "CLOSED",
    "EXPIRED", "MANUAL_REVIEW", "RESOLVED", "DISMISSED",
)
# Quản trị được tính phí ra cho phiên chưa ghi nhận đỗ (ví dụ nút ô hỏng) sau khi kiểm tra tại chỗ.
ADMIN_EXIT_FROM = ("PARKED", "RESERVED", "ENTRY_GATE_OPEN")
EXIT_OPEN_FROM = ("EXIT_REQUESTED", "EXIT_GATE_OPEN")
PRICING_LIMITS = {
    "free_minutes": (0, 1440),
    "first_block_minutes": (1, 1440),
    "first_block_vnd": (0, 10_000_000),
    "extra_hour_vnd": (0, 10_000_000),
}
SUMMARY_FIELDS = (
    "session_id", "session_ref", "state", "lane_id", "slot_id", "review_reason", "created_at", "checkin_at",
    "parked_at", "charge_end_at", "exit_confirmed_at", "fee_vnd", "payment_status", "email_status",
    "plate_confidence",
)
DETAIL_FIELDS = SUMMARY_FIELDS + (
    "card_color", "related_session_id", "resolution", "resolved_session_id", "resolved_from_session_id",
    "claim_expires_at", "entry_command_id", "exit_command_id", "entry_gate_opened_at", "exit_gate_opened_at",
    "gate_error", "paid_amount_vnd", "payment_note", "paid_at", "pricing", "closed_at", "updated_at", "audit",
)


# ---------- Xem ----------

def list_sessions(app: App, req: Request):
    """Mới nhất trước; `?status=` lọc theo trạng thái, `?limit=` 1–100, `?cursor=` lấy trang sau."""
    now = app.clock()
    status = req.query.get("status")
    if status is not None and status not in SESSION_STATES:
        raise ApiError(400, "INVALID_INPUT", "status không hợp lệ")
    try:
        limit = int(req.query.get("limit", 20))
    except ValueError:
        limit = 0
    if not 1 <= limit <= 100:
        raise ApiError(400, "INVALID_INPUT", "limit phải từ 1 đến 100")
    start = _decode_cursor(req.query["cursor"]) if req.query.get("cursor") else None
    t = app.cfg.tables
    try:
        if status:
            items, last = app.db.query_page(t.sessions, "#s = :s", {":s": status}, {"#s": "state"},
                                            index="by_state", descending=True, limit=limit, start_key=start)
        else:
            items, last = app.db.query_page(t.sessions, "site_id = :site", {":site": app.cfg.site_id},
                                            index="by_site", descending=True, limit=limit, start_key=start)
    except ValueError:
        raise ApiError(400, "INVALID_INPUT", "cursor không hợp lệ") from None
    return 200, {"sessions": [_summary(s, now) for s in items], "next_cursor": _encode_cursor(last)}


def get_session(app: App, req: Request, session_id: str):
    return 200, _detail(_session(app, session_id), app.clock())


def list_devices(app: App, req: Request):
    now = app.clock()
    timeout = app.cfg.device_timeout_s
    items = {d["device_id"]: d for d in app.db.batch_get(app.cfg.tables.devices, [{"device_id": d} for d in DEVICES])}
    devices = []
    for device_id in DEVICES:
        item = items.get(device_id) or {}
        view = {
            "device_id": device_id,
            "online": device_online(item, now, timeout),
            "state": item.get("state"),
            "last_seen_at": item.get("last_seen_at"),
            "firmware_version": item.get("firmware_version"),
        }
        if device_id == GATE:
            view["gates"] = {gate: {
                "state": item.get(f"{gate.lower()}_gate_state"),
                "error_code": item.get(f"{gate.lower()}_gate_error"),
                "updated_at": item.get(f"{gate.lower()}_gate_at"),
            } for gate in GATES}
            view["display"] = {"state": item.get("display_state"), "updated_at": item.get("display_at")}
        if device_id == SLOTS:
            view["last_snapshot_at"] = item.get("last_snapshot_at")
            view["snapshot_fresh"] = board_fresh(item, now, timeout)
        devices.append(view)
    return 200, {"devices": devices}


def get_pricing(app: App, req: Request):
    return 200, _pricing_view(app.db.get(app.cfg.tables.pricing, {"pricing_id": "current"}))


# ---------- Xử lý phiên ----------

def resolve_plate(app: App, req: Request, session_id: str):
    """Phiên MANUAL_REVIEW: nhập biển số đúng rồi cho vào (ENTRY), tính phí ra (EXIT) hoặc bỏ qua (DISMISS)."""
    now = app.clock()
    key = idempotency_key(req)
    body = json_body(req)
    action = body.get("action")
    if action not in ("ENTRY", "EXIT", "DISMISS"):
        raise ApiError(400, "INVALID_INPUT", "action phải là ENTRY, EXIT hoặc DISMISS")
    reason = text_field(body, "reason", required=True)
    plate = None
    if action != "DISMISS":
        plate = normalize_plate(body.get("plate_text") if isinstance(body.get("plate_text"), str) else None)
        if not plate:
            raise ApiError(400, "INVALID_INPUT", "plate_text không đúng mẫu biển số")
    review = _session(app, session_id)
    if review.get("resolve_idempotency_key") == key:
        return 200, _resolution(app, review, now)
    if review["state"] != "MANUAL_REVIEW":
        raise ApiError(409, "INVALID_STATE", "Phiên không ở trạng thái chờ xử lý")

    def lead(target_id: str | None) -> dict:
        update, names, values = set_clause({
            "state": "DISMISSED" if action == "DISMISS" else "RESOLVED",
            "resolution": action,
            "resolved_session_id": target_id,
            "resolved_at": iso(now),
            "resolve_idempotency_key": key,
            "updated_at": iso(now),
        }, appends={"audit": [_audit(req, "resolve-plate", now, reason, action)]})
        return op_update(app.cfg.tables.sessions, {"session_id": session_id}, update,
                         "#st = :review AND " + _unused("resolve_idempotency_key"),
                         {**values, ":review": "MANUAL_REVIEW", ":idem": key}, {**names, "#st": "state"})

    commands = []
    if action == "DISMISS":
        try:
            app.db.transact([lead(None)])
        except TransactionCancelled as e:
            if e.failed(0):
                return _replay_or_conflict(app, session_id, "resolve_idempotency_key", key, _resolution)
            raise
    elif action == "ENTRY":
        new_id = new_ulid(now)
        result = reserve_slot(app, lead(new_id), new_id, plate, None, None, now,
                              extra={"resolved_from_session_id": session_id})
        if result.outcome == "LEAD_FAILED":
            return _replay_or_conflict(app, session_id, "resolve_idempotency_key", key, _resolution)
        if result.outcome == "PLATE_ACTIVE":
            raise ApiError(409, "INVALID_STATE", "Biển số này đang có phiên chưa đóng")
        if result.outcome == "SLOTS_UNKNOWN":
            raise ApiError(503, "DEVICE_OFFLINE", "Không có dữ liệu ô mới từ slots-01")
        if result.outcome == "LOT_FULL":
            raise ApiError(409, "SLOT_CONFLICT", "Bãi đầy, không còn ô trống")
        commands = result.commands
    else:
        active = app.db.get(app.cfg.tables.active_plates, {"plate_normalized": plate})
        target = active and app.db.get(app.cfg.tables.sessions, {"session_id": active["session_id"]})
        if not target or target["state"] not in ADMIN_EXIT_FROM:
            raise ApiError(409, "INVALID_STATE", "Không có phiên đang đỗ cho biển số này")
        # Phí khóa ở lúc xe đến cổng ra (lúc tạo phiên chờ xử lý), không tăng trong lúc quản trị kiểm tra.
        result = request_exit(app, lead(target["session_id"]), target, parse_iso(review["created_at"]),
                              ADMIN_EXIT_FROM, now)
        if result.outcome == "LEAD_FAILED":
            return _replay_or_conflict(app, session_id, "resolve_idempotency_key", key, _resolution)
        if result.outcome == "NOT_PARKED":
            raise ApiError(409, "INVALID_STATE", "Phiên của biển số này vừa đổi trạng thái")
        commands = result.commands
    sent = _publish_best_effort(app, commands)
    return 200, {**_resolution(app, _session(app, session_id), now), "commands_sent": sent}


def renew_claim(app: App, req: Request, session_id: str):
    """QR mới (nonce và hạn mới); QR cũ hết hiệu lực ngay. Gửi lại cùng key trả lại đúng URL đó."""
    now = app.clock()
    key = idempotency_key(req)
    reason = text_field(json_body(req, optional=True), "reason")
    session = _session(app, session_id)
    if session.get("renew_idempotency_key") != key:
        if session["state"] not in CLAIM_STATES:
            raise ApiError(409, "INVALID_STATE", "Chỉ cấp lại QR cho xe còn trong bãi")
        states = {f":c{i}": s for i, s in enumerate(CLAIM_STATES)}
        _guarded_update(app, req, session_id, "renew_idempotency_key", key, {
            "claim_nonce": new_nonce(),
            "claim_expires_at": iso(from_epoch(epoch(now) + app.cfg.claim_ttl_s)),
            "claim_pk": app.cfg.site_id,
            "updated_at": iso(now),
        }, _audit(req, "renew-claim", now, reason), f"#st IN ({', '.join(states)})", states)
        session = _session(app, session_id)
    return 200, claim_summary(app, session, app.keys.keys())


def record_payment(app: App, req: Request, session_id: str):
    """PAID_CASH phải đúng số tiền đã khóa; WAIVED bắt buộc ghi chú. Sau đó phiên sẵn sàng mở cần ra."""
    now = app.clock()
    key = idempotency_key(req)
    body = json_body(req)
    status, amount = body.get("payment_status"), body.get("amount_vnd")
    if status not in ("PAID_CASH", "WAIVED"):
        raise ApiError(400, "INVALID_INPUT", "payment_status phải là PAID_CASH hoặc WAIVED")
    note = text_field(body, "note", required=status == "WAIVED")
    if status == "PAID_CASH" and not (type(amount) is int and amount >= 0):
        raise ApiError(400, "INVALID_INPUT", "amount_vnd phải là số nguyên không âm")
    if status == "WAIVED" and amount not in (None, 0):
        raise ApiError(400, "INVALID_INPUT", "Miễn phí thì amount_vnd bỏ trống hoặc bằng 0")
    session = _session(app, session_id)
    if session.get("payment_idempotency_key") != key:
        if session["state"] != "PAYMENT_PENDING" or session.get("payment_status") != "PENDING":
            raise ApiError(409, "INVALID_STATE", "Phiên không ở trạng thái chờ thu tiền")
        if status == "PAID_CASH" and amount != session["fee_vnd"]:
            raise ApiError(409, "INVALID_STATE", f"Số tiền phải bằng phí đã chốt {session['fee_vnd']} ₫")
        _guarded_update(app, req, session_id, "payment_idempotency_key", key, {
            "state": "EXIT_REQUESTED",
            "payment_status": status,
            "paid_amount_vnd": amount or 0,
            "payment_note": note,
            "paid_at": iso(now),
            "updated_at": iso(now),
        }, _audit(req, "payment", now, note, status), "#st = :pending_state AND payment_status = :pending AND fee_vnd = :fee",
            {":pending_state": "PAYMENT_PENDING", ":pending": "PENDING", ":fee": session["fee_vnd"]})
        session = _session(app, session_id)
    return 200, _detail(session, now)


def open_exit(app: App, req: Request, session_id: str):
    """Phát lệnh mở cần ra khi phí đã xong (NO_CHARGE/PAID_CASH/WAIVED) và gate-01 đang online."""
    now = app.clock()
    key = idempotency_key(req)
    reason = text_field(json_body(req, optional=True), "reason")
    session = _session(app, session_id)
    if session.get("exit_open_idempotency_key") == key:
        return 202, {"command_id": session.get("exit_command_id"), "session": _detail(session, now)}
    if session["state"] not in EXIT_OPEN_FROM or session.get("payment_status") not in PAID_STATUSES:
        raise ApiError(409, "INVALID_STATE", "Phiên chưa yêu cầu ra hoặc chưa thu tiền")
    t = app.cfg.tables
    if not device_online(app.db.get(t.devices, {"device_id": GATE}), now, app.cfg.device_timeout_s):
        raise ApiError(503, "DEVICE_OFFLINE", "gate-01 đang mất kết nối, không thể mở cần an toàn")
    topic, cmd = gate_command(app.cfg.site_id, "EXIT", "OPEN", session_id, now, app.cfg.gate_command_ttl_s)
    update, names, values = set_clause({
        "exit_command_id": cmd["command_id"],
        "exit_open_requested_at": iso(now),
        "exit_open_idempotency_key": key,
        "updated_at": iso(now),
    }, appends={"audit": [_audit(req, "open-exit", now, reason)]})
    states = {f":o{i}": s for i, s in enumerate(EXIT_OPEN_FROM)}
    paid = {f":p{i}": s for i, s in enumerate(PAID_STATUSES)}
    condition = (f"#st IN ({', '.join(states)}) AND payment_status IN ({', '.join(paid)}) AND "
                 + _unused("exit_open_idempotency_key"))
    try:
        app.db.transact([
            op_update(t.sessions, {"session_id": session_id}, update, condition,
                      {**values, **states, **paid, ":idem": key}, {**names, "#st": "state"}),
            command_record_op(app, cmd, session_id, ["EXIT_REQUESTED"], "EXIT_GATE_OPEN", now),
        ])
    except TransactionCancelled as e:
        if e.failed(0):
            latest = _session(app, session_id)
            if latest.get("exit_open_idempotency_key") == key:
                return 202, {"command_id": latest.get("exit_command_id"), "session": _detail(latest, now)}
            raise ApiError(409, "INVALID_STATE", "Phiên vừa đổi trạng thái, tải lại") from None
        raise
    try:
        publish(app, [(topic, cmd)])
    except PublishFailed:
        # Bỏ key để lần bấm lại (cùng key) phát lệnh mới thay vì trả "đã mở".
        app.db.update(t.sessions, {"session_id": session_id}, "REMOVE exit_open_idempotency_key",
                      "exit_open_idempotency_key = :idem", {":idem": key})
        raise ApiError(503, "DEVICE_OFFLINE", "Không gửi được lệnh tới cổng, thử lại") from None
    _publish_best_effort(app, [display_command(app.cfg.site_id, "EXIT_FEE", ["RA - MOI XE QUA", "Cam on quy khach"],
                                               now, app.cfg.display_command_ttl_s)])
    return 202, {"command_id": cmd["command_id"], "session": _detail(_session(app, session_id), now)}


def confirm_passage(app: App, req: Request, session_id: str):
    """Xe đã qua cần ra: đóng phiên, bỏ khóa biển số và giữ ô, xóa email. Ô về AVAILABLE khi cảm biến báo trống."""
    now = app.clock()
    key = idempotency_key(req)
    reason = text_field(json_body(req, optional=True), "reason")
    session = _session(app, session_id)
    if session.get("confirm_idempotency_key") == key:
        return 200, _detail(session, now)
    if session["state"] not in EXIT_OPEN_FROM or not session.get("exit_command_id") \
            or session.get("payment_status") not in PAID_STATUSES:
        raise ApiError(409, "INVALID_STATE", "Chưa mở cần ra cho phiên này")
    t = app.cfg.tables
    update, names, values = set_clause({
        "state": "CLOSED",
        "exit_confirmed_at": iso(now),
        "closed_at": iso(now),
        "confirm_idempotency_key": key,
        "updated_at": iso(now),
        "email": None,
        "claim_pk": None,
        "claim_nonce": None,
    }, appends={"audit": [_audit(req, "confirm-passage", now, reason)]})
    states = {f":o{i}": s for i, s in enumerate(EXIT_OPEN_FROM)}
    ops = [op_update(t.sessions, {"session_id": session_id}, update,
                     f"#st IN ({', '.join(states)}) AND attribute_exists(exit_command_id) AND "
                     + _unused("confirm_idempotency_key"),
                     {**values, **states, ":idem": key}, {**names, "#st": "state"})]
    plate = session.get("plate_normalized")
    active = plate and app.db.get(t.active_plates, {"plate_normalized": plate})
    if active and active.get("session_id") == session_id:
        ops.append(op_delete(t.active_plates, {"plate_normalized": plate}, "session_id = :sid", {":sid": session_id}))
    slot = session.get("slot_id") and app.db.get(t.slots, {"slot_id": session["slot_id"]})
    if slot and slot.get("reserved_session_id") == session_id:
        ops.append(op_update(t.slots, {"slot_id": session["slot_id"]},
                             "SET updated_at = :now REMOVE reserved_session_id, reserved_at",
                             "reserved_session_id = :sid", {":now": iso(now), ":sid": session_id}))
    try:
        app.db.transact(ops)
    except TransactionCancelled as e:
        if e.failed(0):
            return _replay_or_conflict(app, session_id, "confirm_idempotency_key", key, lambda a, s, n: _detail(s, n))
        raise ApiError(409, "INVALID_STATE", "Dữ liệu ô hoặc biển số vừa thay đổi, thử lại") from None
    return 200, _detail(_session(app, session_id), now)


def put_pricing(app: App, req: Request):
    """Tăng version mỗi lần sửa. Phiên đang mở giữ bảng giá đã chép lúc check-in."""
    now = app.clock()
    key = idempotency_key(req)
    body = json_body(req)
    rules = {}
    for name, (low, high) in PRICING_LIMITS.items():
        value = body.get(name)
        if type(value) is not int or not low <= value <= high:
            raise ApiError(400, "INVALID_INPUT", f"{name} phải là số nguyên từ {low} đến {high}")
        rules[name] = value
    if rules["first_block_minutes"] < rules["free_minutes"]:
        raise ApiError(400, "INVALID_INPUT", "first_block_minutes không được nhỏ hơn free_minutes")
    reason = text_field(body, "reason")
    t = app.cfg.tables
    current = app.db.get(t.pricing, {"pricing_id": "current"})
    if current and current.get("idempotency_key") == key:
        return 200, _pricing_view(current)
    version = (current or {}).get("rules", DEFAULT_PRICING)["version"]
    update, names, values = set_clause({
        "rules": {"version": version + 1, **rules},
        "updated_at": iso(now),
        "updated_by": req.actor["actor_id"],
        "idempotency_key": key,
    }, appends={"audit": [_audit(req, "put-pricing", now, reason, f"version {version + 1}")]})
    try:
        app.db.update(t.pricing, {"pricing_id": "current"}, update,
                      "(attribute_not_exists(pricing_id) OR #r.#v = :ver) AND " + _unused("idempotency_key"),
                      {**values, ":ver": version, ":idem": key}, {**names, "#r": "rules", "#v": "version"})
    except ConditionFailed:
        latest = app.db.get(t.pricing, {"pricing_id": "current"}) or {}
        if latest.get("idempotency_key") == key:
            return 200, _pricing_view(latest)
        raise ApiError(409, "INVALID_STATE", "Bảng giá vừa được sửa, tải lại rồi thử lại") from None
    return 200, _pricing_view(app.db.get(t.pricing, {"pricing_id": "current"}))


# ---------- Tiện ích ----------

def _session(app: App, session_id: str) -> dict:
    session = app.db.get(app.cfg.tables.sessions, {"session_id": session_id})
    if not session:
        raise ApiError(404, "NOT_FOUND", "Không tìm thấy phiên")
    return session


def _unused(field: str) -> str:
    return f"(attribute_not_exists({field}) OR {field} <> :idem)"


def _audit(req: Request, action: str, now: datetime, reason: str | None = None, detail: str | None = None) -> dict:
    entry = {"action": action, "at": iso(now), **req.actor}
    if reason:
        entry["reason"] = reason
    if detail:
        entry["detail"] = detail
    return entry


def _guarded_update(app: App, req: Request, session_id: str, key_field: str, key: str, fields: dict, audit: dict,
                    condition: str, values: dict):
    """Ghi khi điều kiện trạng thái đúng và key chưa dùng; cùng key đã áp dụng thì coi như thành công."""
    update, names, set_values = set_clause({**fields, key_field: key}, appends={"audit": [audit]})
    try:
        app.db.update(app.cfg.tables.sessions, {"session_id": session_id}, update,
                      f"({condition}) AND {_unused(key_field)}",
                      {**set_values, **values, ":idem": key}, {**names, "#st": "state"})
    except ConditionFailed:
        if _session(app, session_id).get(key_field) != key:
            raise ApiError(409, "INVALID_STATE", "Phiên vừa đổi trạng thái, tải lại") from None


def _replay_or_conflict(app: App, session_id: str, key_field: str, key: str, view):
    latest = _session(app, session_id)
    if latest.get(key_field) == key:
        return 200, view(app, latest, app.clock())
    raise ApiError(409, "INVALID_STATE", "Phiên vừa đổi trạng thái, tải lại")


def _publish_best_effort(app: App, commands: list) -> bool:
    """Dữ liệu đã ghi; lệnh lỗi chỉ báo về cho quản trị (thao tác tay tại mô hình)."""
    try:
        publish(app, commands)
        return True
    except PublishFailed:
        return False


def _visible_identity(session: dict, now: datetime) -> dict:
    """Biển số/email chỉ trả khi chưa quá hạn 10 ngày, kể cả khi job purge chưa kịp xóa."""
    plate_ok = session.get("identity_expires_at", "") > iso(now)
    email_ok = session.get("email_expires_at", "") > iso(now)
    return {
        "plate_normalized": session.get("plate_normalized") if plate_ok else None,
        "plate_text": session.get("plate_text") if plate_ok else None,
        "email": session.get("email") if email_ok else None,
    }


def _summary(session: dict, now: datetime) -> dict:
    return {**{k: session.get(k) for k in SUMMARY_FIELDS},
            "plate_normalized": _visible_identity(session, now)["plate_normalized"]}


def _detail(session: dict, now: datetime) -> dict:
    return {**{k: session.get(k) for k in DETAIL_FIELDS}, **_visible_identity(session, now)}


def _resolution(app: App, review: dict, now: datetime) -> dict:
    target_id = review.get("resolved_session_id")
    target = target_id and app.db.get(app.cfg.tables.sessions, {"session_id": target_id})
    return {"review": _detail(review, now), "session": _detail(target, now) if target else None}


def _pricing_view(item: dict | None) -> dict:
    item = item or {}
    return {**item.get("rules", DEFAULT_PRICING), "updated_at": item.get("updated_at"),
            "updated_by": item.get("updated_by")}


def _encode_cursor(key: dict | None) -> str | None:
    if not key:
        return None
    return base64.urlsafe_b64encode(json.dumps(key, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode_cursor(raw: str) -> dict:
    try:
        key = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError:
        raise ApiError(400, "INVALID_INPUT", "cursor không hợp lệ") from None
    valid = isinstance(key, dict) and 0 < len(key) <= 4 and all(
        isinstance(v, dict) and set(v) == {"S"} and isinstance(v["S"], str) for v in key.values())
    if not valid:
        raise ApiError(400, "INVALID_INPUT", "cursor không hợp lệ")
    return key


ADMIN = {"ADMIN"}
SESSION = r"(?P<session_id>[0-9A-HJKMNP-TV-Z]{26})"
ROUTES = [
    ("GET", re.compile(r"/admin/sessions"), list_sessions, ADMIN),
    ("GET", re.compile(rf"/admin/sessions/{SESSION}"), get_session, ADMIN),
    ("POST", re.compile(rf"/admin/sessions/{SESSION}/resolve-plate"), resolve_plate, ADMIN),
    ("POST", re.compile(rf"/admin/sessions/{SESSION}/renew-claim"), renew_claim, ADMIN),
    ("POST", re.compile(rf"/admin/sessions/{SESSION}/payment"), record_payment, ADMIN),
    ("POST", re.compile(rf"/admin/sessions/{SESSION}/open-exit"), open_exit, ADMIN),
    ("POST", re.compile(rf"/admin/sessions/{SESSION}/confirm-passage"), confirm_passage, ADMIN),
    ("GET", re.compile(r"/admin/devices"), list_devices, ADMIN),
    ("GET", re.compile(r"/admin/pricing"), get_pricing, ADMIN),
    ("PUT", re.compile(r"/admin/pricing"), put_pricing, ADMIN),
]
