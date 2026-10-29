"""Lambda HTTP API v1 (docs/api-contract.md): public, guest QR, kiosk; endpoint quản trị ở admin.py.

API Gateway (JWT authorizer Cognito) xác thực kiosk/admin; Lambda vẫn kiểm nhóm để không dựa vào
cấu hình route. Mọi lỗi trả `{code, message, request_id}`, kể cả lỗi 500 (`INTERNAL_ERROR`).
"""
import re
import traceback
from collections import Counter
from datetime import timedelta

from . import admin
from .app import App, get_app
from .claims import InvalidToken, verify_claim
from .contract import DEVICES, GATE, SLOTS
from .flows import claim_summary
from .ids import new_uuid
from .jobs import CLOSED_STATES
from .layout import SLOT_IDS, route_steps, source_of
from .log import log
from .rest import ApiError, Request, authorize, idempotency_key, json_body, parse_event, response
from .state import CLAIM_STATES, board_fresh, cutoff, device_online, slot_status
from .store import ConditionFailed, set_clause
from .timeutil import epoch, iso, parse_iso

EMAIL_RE = re.compile(r"[^\s@]{1,64}@[^\s@]+\.[^\s@]{2,}")


def handler(event, _context):
    return handle(get_app(), event)


def handle(app: App, event: dict) -> dict:
    request_id = event.get("requestContext", {}).get("requestId") or new_uuid()
    route_name = "unknown"
    try:
        req = parse_event(event)
        for method, pattern, fn, roles in ROUTES:
            match = pattern.fullmatch(req.path)
            if match and method == req.method:
                route_name = fn.__name__
                if roles:
                    authorize(req, roles)
                status, body = fn(app, req, **match.groupdict())
                return response(status, body)
        raise ApiError(404, "NOT_FOUND", "Không có endpoint này")
    except ApiError as e:
        return response(e.status, {"code": e.code, "message": e.message, "request_id": request_id})
    except Exception as e:
        # Không log path/body vì có thể chứa token hoặc email.
        log("api_error", request_id=request_id, route=route_name, error=type(e).__name__,
            trace="".join(traceback.format_tb(e.__traceback__)))
        return response(500, {"code": "INTERNAL_ERROR", "message": "Lỗi máy chủ", "request_id": request_id})


# ---------- Public và guest ----------

def get_layout(app: App, req: Request):
    now = app.clock()
    t = app.cfg.tables
    slots = {s["slot_id"]: s for s in app.db.batch_get(t.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
    board = app.db.get(t.devices, {"device_id": SLOTS}, consistent=False)
    fresh = board_fresh(board, now, app.cfg.device_timeout_s)
    snapshot_at = (board or {}).get("last_snapshot_at")
    return 200, {"slots": [
        {
            "slot_id": sid,
            "source": source_of(sid),
            "status": slot_status(slots.get(sid), fresh),
            # Thời điểm backend xác nhận trạng thái gần nhất: lần đổi của ô hoặc snapshot mới nhất.
            "updated_at": max(filter(None, [slots.get(sid, {}).get("updated_at"), snapshot_at]), default=None),
        }
        for sid in SLOT_IDS
    ]}


def get_claim(app: App, req: Request, token: str):
    session = _load_claim(app, token)
    return 200, {
        "session_ref": session["session_ref"],
        "slot_id": session["slot_id"],
        "route_steps": route_steps(session["slot_id"]),
        "claim_expires_at": session["claim_expires_at"],
        "email_submitted": "email_status" in session,
    }


def post_claim_email(app: App, req: Request, token: str):
    """Một email hướng dẫn cho mỗi phiên. Gửi lại cùng Idempotency-Key trả 202 mà không gửi lần hai."""
    now = app.clock()
    t = app.cfg.tables
    key = idempotency_key(req)
    session = _load_claim(app, token)
    body = json_body(req)
    email, consent = body.get("email"), body.get("consent_for_this_session")
    email = email.strip() if isinstance(email, str) else ""
    if len(email) > 254 or not EMAIL_RE.fullmatch(email) or consent is not True:
        raise ApiError(400, "INVALID_INPUT", "Email không hợp lệ hoặc chưa đồng ý nhận email")
    update, names, values = set_clause({
        "email_status": "QUEUED",
        "email": email,
        "email_collected_at": iso(now),
        "email_expires_at": iso(now + timedelta(seconds=app.cfg.identity_retention_s)),
        "email_idempotency_key": key,
        "updated_at": iso(now),
    })
    try:
        app.db.update(t.sessions, {"session_id": session["session_id"]}, update,
                      "attribute_not_exists(#f0) AND claim_nonce = :nonce AND claim_expires_at > :now_iso",
                      {**values, ":nonce": session["claim_nonce"], ":now_iso": iso(now)}, names)
    except ConditionFailed:
        latest = app.db.get(t.sessions, {"session_id": session["session_id"]}) or {}
        if latest.get("email_idempotency_key") == key:
            return 202, {"email_status": "QUEUED"}
        if "email_status" in latest:
            raise ApiError(409, "EMAIL_ALREADY_SENT", "Phiên này đã gửi email hướng dẫn") from None
        raise ApiError(410, "TOKEN_EXPIRED", "Mã QR đã hết hạn") from None
    _send_guidance(app, session, email)
    return 202, {"email_status": "QUEUED"}


def _send_guidance(app: App, session: dict, email: str):
    """SES lỗi không làm hỏng phiên: khách vẫn có lộ trình trên web/OLED, quản trị thấy FAILED (SIM-14)."""
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(route_steps(session["slot_id"]), 1))
    text = (
        "Xin chào,\n\n"
        f"Lượt gửi xe {session['session_ref']} của bạn được xếp vào ô {session['slot_id']}.\n\n"
        f"Đường đi:\n{steps}\n\n"
        "Email này chỉ dùng cho lượt gửi xe hiện tại và được xóa sau tối đa 10 ngày.\n"
        "Smart Parking (đồ án mô phỏng)\n"
    )
    subject = f"Chỉ dẫn đỗ xe: ô {session['slot_id']} (mã lượt {session['session_ref']})"
    now = app.clock()
    try:
        message_id = app.mailer.send(email, subject, text)
        fields = {"email_status": "ACCEPTED_BY_SES", "ses_message_id": message_id, "updated_at": iso(now)}
    except Exception as e:
        log("email_failed", session_id=session["session_id"], error=type(e).__name__)
        fields = {"email_status": "FAILED", "email_error": type(e).__name__, "updated_at": iso(now)}
    update, names, values = set_clause(fields)
    app.db.update(app.cfg.tables.sessions, {"session_id": session["session_id"]}, update, values=values, names=names)


def _load_claim(app: App, token: str) -> dict:
    """Token sai chữ ký → 404 (không lộ phiên nào tồn tại); hết hạn, đã cấp lại hoặc phiên đã xong → 410."""
    now = app.clock()
    try:
        ref = verify_claim(app.keys.keys(), token)
    except InvalidToken:
        raise ApiError(404, "NOT_FOUND", "Không tìm thấy lượt gửi xe") from None
    session = app.db.get(app.cfg.tables.sessions, {"session_id": ref.session_id})
    if not session:
        raise ApiError(404, "NOT_FOUND", "Không tìm thấy lượt gửi xe")
    expires_at = session.get("claim_expires_at")
    current = session.get("claim_nonce") == ref.nonce and expires_at \
        and epoch(parse_iso(expires_at)) == ref.expires_epoch
    if not current or ref.expires_epoch <= epoch(now) or session.get("state") not in CLAIM_STATES:
        raise ApiError(410, "TOKEN_EXPIRED", "Mã QR đã hết hạn")
    return session


# ---------- Kiosk và dashboard ----------

def get_active_claims(app: App, req: Request):
    """Phiên còn hạn QR, mới nhất trước. Thêm `route_steps`, `created_at` so với hợp đồng để kiosk hiện lộ trình."""
    now = app.clock()
    keys = app.keys.keys()
    items = app.db.query(app.cfg.tables.sessions, "claim_pk = :site AND claim_expires_at > :now",
                         {":site": app.cfg.site_id, ":now": iso(now)}, index="active_claims")
    claims = [claim_summary(app, s, keys) for s in items if s.get("state") in CLAIM_STATES]
    claims.sort(key=lambda c: c["created_at"], reverse=True)
    return 200, claims


def get_dashboard(app: App, req: Request):
    now = app.clock()
    cfg, t = app.cfg, app.cfg.tables
    slots = {s["slot_id"]: s for s in app.db.batch_get(t.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
    devices = {d["device_id"]: d for d in app.db.batch_get(t.devices, [{"device_id": d} for d in DEVICES])}
    fresh = board_fresh(devices.get(SLOTS), now, cfg.device_timeout_s)
    counts = Counter(slot_status(slots.get(sid), fresh) for sid in SLOT_IDS)
    offline = [d for d in DEVICES if not device_online(devices.get(d), now, cfg.device_timeout_s)]
    return 200, {
        "available": counts["AVAILABLE"],
        "reserved": counts["RESERVED"],
        "occupied": counts["OCCUPIED"],
        "unknown": counts["UNKNOWN"],
        "offline_devices": offline,
        "alerts": _alerts(app, slots, devices, offline, fresh, now),
    }


def _alerts(app: App, slots: dict, devices: dict, offline: list, fresh: bool, now) -> list[str]:
    """Cảnh báo suy ra từ dữ liệu hiện có; không chứa biển số/email."""
    alerts = [f"Thiết bị {d} mất kết nối" for d in offline]
    if not fresh and SLOTS not in offline:
        alerts.append("Không có snapshot ô mới: mọi ô đang UNKNOWN")
    late = cutoff(now, app.cfg.reservation_timeout_s)
    for sid in SLOT_IDS:
        slot = slots.get(sid) or {}
        if fresh and slot.get("occupied") and not slot.get("reserved_session_id"):
            alerts.append(f"Ô {sid} có xe nhưng không có phiên được gán")
        if slot.get("reserved_session_id") and not slot.get("occupied") and slot.get("reserved_at", "") < late:
            alerts.append(f"Ô {sid} giữ quá {app.cfg.reservation_timeout_s // 60} phút chưa có xe")
    gate = devices.get(GATE) or {}
    for lane in ("entry", "exit"):
        if gate.get(f"{lane}_gate_state") == "ERROR":
            alerts.append(f"Cần {lane.upper()} báo lỗi {gate.get(f'{lane}_gate_error') or 'không rõ'}")
    t = app.cfg.tables
    review = app.db.query(t.sessions, "#s = :s", {":s": "MANUAL_REVIEW"}, {"#s": "state"}, index="by_state")
    if review:
        alerts.append(f"{len(review)} lượt chờ quản trị xử lý")
    hour_ago = cutoff(now, 3600)
    expired = app.db.query(t.sessions, "#s = :s AND created_at >= :since",
                           {":s": "EXPIRED", ":since": cutoff(now, 3600 + app.cfg.reservation_timeout_s)},
                           {"#s": "state"}, index="by_state")
    expired = [s for s in expired if s.get("expired_at", "") >= hour_ago]
    if expired:
        alerts.append(f"{len(expired)} lượt giữ ô hết hạn trong 1 giờ qua (xe không vào ô được gán)")
    due_soon = app.db.query(t.sessions, "pii_pk = :site AND purge_due_at <= :soon",
                            {":site": app.cfg.site_id, ":soon": iso(now + timedelta(days=1))}, index="purge_due")
    if due_soon:
        sessions = app.db.batch_get(t.sessions, [{"session_id": k["session_id"]} for k in due_soon])
        still_open = [s for s in sessions if s.get("state") not in CLOSED_STATES]
        if still_open:
            alerts.append(f"{len(still_open)} phiên còn mở sẽ bị xóa biển số trong 24 giờ: cần đóng hoặc xử lý")
    return alerts


TOKEN = r"(?P<token>[A-Za-z0-9._-]{1,200})"
ROUTES = [
    ("GET", re.compile(r"/public/layout"), get_layout, None),
    ("GET", re.compile(rf"/public/claims/{TOKEN}"), get_claim, None),
    ("POST", re.compile(rf"/public/claims/{TOKEN}/email"), post_claim_email, None),
    ("GET", re.compile(r"/kiosk/active-claims"), get_active_claims, {"KIOSK", "ADMIN"}),
    ("GET", re.compile(r"/admin/dashboard"), get_dashboard, {"ADMIN"}),
    *admin.ROUTES,
]
