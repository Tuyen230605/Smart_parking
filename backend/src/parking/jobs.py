"""Lambda chạy theo lịch (EventBridge Scheduler), payload `{"job": ...}`:

- `expire_reservations` (mỗi phút): phiên giữ ô quá 5 phút mà ô chưa báo có xe → EXPIRED, bỏ giữ ô khi ô
  vẫn trống, bỏ khóa biển số và QR (UC-05, SIM-13).
- `purge_identity` (mỗi giờ): xóa biển số/email của phiên tới `purge_due_at` (9 ngày 23 giờ), kể cả phiên
  còn mở; dashboard cảnh báo trước 24 giờ để quản trị đóng phiên (UC-10, SIM-16).

Cả hai idempotent: chạy lại hay chạy chồng không đổi kết quả. Lỗi hạ tầng ném ra để alarm báo.
"""
from datetime import datetime

from .app import App, get_app
from .log import log
from .state import cutoff
from .store import TransactionCancelled, op_delete, op_update, set_clause
from .timeutil import iso

UNPARKED_STATES = ("RESERVED", "ENTRY_GATE_OPEN")
SYSTEM_ACTOR = {"actor_id": "system", "actor": "scheduler"}


def handler(event, _context):
    job = (event or {}).get("job")
    if job not in JOBS:
        raise ValueError(f"job không hỗ trợ: {job}")
    result = JOBS[job](get_app())
    log("job_done", job=job, **result)
    return result


def expire_reservations(app: App) -> dict:
    now = app.clock()
    late = cutoff(now, app.cfg.reservation_timeout_s)
    expired = skipped = 0
    for state in UNPARKED_STATES:
        # Index đọc không nhất quán ngay: điều kiện trong transaction mới là chốt chặn.
        for session in app.db.query(app.cfg.tables.sessions, "#s = :s AND created_at <= :late",
                                    {":s": state, ":late": late}, {"#s": "state"}, index="by_state"):
            if _expire(app, session["session_id"], now):
                expired += 1
            else:
                skipped += 1
    return {"expired": expired, "skipped": skipped}


def _expire(app: App, session_id: str, now: datetime) -> bool:
    t = app.cfg.tables
    session = app.db.get(t.sessions, {"session_id": session_id})
    if not session or session.get("state") not in UNPARKED_STATES:
        return False
    slot = session.get("slot_id") and app.db.get(t.slots, {"slot_id": session["slot_id"]})
    if slot and slot.get("reserved_session_id") == session_id and slot.get("occupied"):
        return False  # xe đang ở ô: ACK/cảm biến sẽ chuyển PARKED, không giải phóng
    update, names, values = set_clause({
        "state": "EXPIRED",
        "expired_at": iso(now),
        "updated_at": iso(now),
        "claim_pk": None,
        "claim_nonce": None,
    }, appends={"audit": [{"action": "expire-reservation", "at": iso(now), **SYSTEM_ACTOR}]})
    ops = [op_update(t.sessions, {"session_id": session_id}, update, "#f0 IN (:reserved, :gate_open)",
                     {**values, ":reserved": "RESERVED", ":gate_open": "ENTRY_GATE_OPEN"}, names)]
    ops += _release_plate_ops(app, session)
    if slot and slot.get("reserved_session_id") == session_id:
        ops.append(op_update(t.slots, {"slot_id": session["slot_id"]},
                             "SET updated_at = :now REMOVE reserved_session_id, reserved_at",
                             "reserved_session_id = :sid AND occupied = :false",
                             {":now": iso(now), ":sid": session_id, ":false": False}))
    try:
        app.db.transact(ops)
    except TransactionCancelled:
        return False  # phiên vừa đỗ hoặc ô vừa có xe: lần chạy sau xét lại
    log("reservation_expired", session_id=session_id, slot_id=session.get("slot_id"))
    return True


def purge_identity(app: App) -> dict:
    now = app.clock()
    keys = app.db.query(app.cfg.tables.sessions, "pii_pk = :site AND purge_due_at <= :now",
                        {":site": app.cfg.site_id, ":now": iso(now)}, index="purge_due")
    purged = open_sessions = 0
    for key in keys:
        result = _purge(app, key["session_id"], now)
        purged += result is not None
        open_sessions += result == "OPEN"
    if open_sessions:
        log("purged_open_sessions", count=open_sessions)
    return {"purged": purged, "open_sessions": open_sessions}


def _purge(app: App, session_id: str, now: datetime) -> str | None:
    """Xóa thuộc tính định danh, giữ phí/thời gian để báo cáo. Trả "OPEN" nếu phiên chưa kết thúc."""
    t = app.cfg.tables
    session = app.db.get(t.sessions, {"session_id": session_id})
    if not session or "pii_pk" not in session:
        return None
    update, names, values = set_clause({
        "plate_normalized": None,
        "plate_text": None,
        "plate_collected_at": None,
        "email": None,
        "email_collected_at": None,
        "claim_nonce": None,
        "claim_pk": None,
        "pii_pk": None,
        "purge_due_at": None,
        "identity_purged_at": iso(now),
        "updated_at": iso(now),
    }, appends={"audit": [{"action": "purge-identity", "at": iso(now), **SYSTEM_ACTOR}]})
    ops = [op_update(t.sessions, {"session_id": session_id}, update, "attribute_exists(#pii)", values,
                     {**names, "#pii": "pii_pk"})]
    ops += _release_plate_ops(app, session)
    try:
        app.db.transact(ops)
    except TransactionCancelled as e:
        if e.failed(0):
            return None  # lần chạy khác vừa xóa
        raise
    return "OPEN" if session.get("state") not in CLOSED_STATES else "DONE"


def _release_plate_ops(app: App, session: dict) -> list[dict]:
    """Bỏ khóa biển số chỉ khi khóa đó thuộc đúng phiên này."""
    plate = session.get("plate_normalized")
    active = plate and app.db.get(app.cfg.tables.active_plates, {"plate_normalized": plate})
    if not active or active.get("session_id") != session["session_id"]:
        return []
    return [op_delete(app.cfg.tables.active_plates, {"plate_normalized": plate}, "session_id = :sid",
                      {":sid": session["session_id"]})]


CLOSED_STATES = ("CLOSED", "EXPIRED", "RESOLVED", "DISMISSED")
JOBS = {
    "expire_reservations": expire_reservations,
    "purge_identity": purge_identity,
}
