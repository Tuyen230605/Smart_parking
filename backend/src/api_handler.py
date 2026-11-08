"""Lambda cho API Gateway HTTP API (payload v2). Route theo docs/api-contract.md.

JWT Cognito đã được API Gateway kiểm tra cho route kiosk/admin; ở đây kiểm tra nhóm.
"""
import base64
import json
import re

import core
import logic
import services
from logic import BusinessError

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def respond(status, body, request_id="-"):
    if status >= 400 and "request_id" not in body:
        body = {**body, "request_id": request_id}
    return {"statusCode": status, "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": core.dumps(body)}


# ── quyền ──────────────────────────────────────────────────────────────────


def _groups(event):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    raw = claims.get("cognito:groups", "")
    if isinstance(raw, list):
        return set(raw), claims
    return set(g for g in re.split(r"[\s,\[\]]+", raw) if g), claims


def require(event, *allowed):
    groups, claims = _groups(event)
    if not claims:
        raise BusinessError(401, "UNAUTHENTICATED", "Cần đăng nhập")
    if not groups & set(allowed):
        raise BusinessError(403, "FORBIDDEN", "Tài khoản không có quyền này")
    return claims.get("username") or claims.get("cognito:username") or claims.get("sub", "unknown")


# ── chuyển đổi dữ liệu ra ngoài ────────────────────────────────────────────


def _identity_visible(session, field_at):
    collected = core.parse_iso(session.get(field_at))
    return bool(collected and core.now() - collected < core.IDENTITY_TTL)


def admin_session_view(s):
    s = core.plain(s)
    out = {k: v for k, v in s.items() if k not in ("claim_nonce", "plate_normalized", "plate_display", "email", "pricing")}
    out["plate_text"] = s.get("plate_display") if _identity_visible(s, "plate_collected_at") else None
    out["email"] = s.get("email") if _identity_visible(s, "email_collected_at") else None
    out["pricing_version"] = (s.get("pricing") or {}).get("version")
    if s.get("state") in ("RESERVED", "PARKED") and s.get("claim_nonce") and _claim_live(s):
        out["claim_url"] = services.claim_url(s)
    if s.get("state") in ("RESERVED", "PARKED"):
        out["fee_preview_vnd"] = services.compute_fee(
            s.get("pricing") or services.current_pricing(), core.parse_iso(s["checkin_at"]), core.now())
    return out


def _claim_live(s):
    exp = core.parse_iso(s.get("claim_expires_at"))
    return bool(exp and core.now() < exp)


def _session_from_token(token):
    data = services.read_token(token)
    if not data:
        raise BusinessError(404, "NOT_FOUND", "Không tìm thấy lượt gửi xe")
    s = core.table("sessions").get_item(Key={"session_id": data["s"]}).get("Item")
    if not s:
        raise BusinessError(404, "NOT_FOUND", "Không tìm thấy lượt gửi xe")
    if s.get("claim_nonce") != data["n"] or core.now().timestamp() >= data["e"] or not _claim_live(s):
        raise BusinessError(410, "TOKEN_EXPIRED", "Mã QR đã hết hạn")
    return s


def _claim_view(s):
    return {
        "session_ref": s["session_ref"],
        "slot_id": s["slot_id"],
        "route_steps": core.route_steps(s["slot_id"]),
        "claim_expires_at": s["claim_expires_at"],
        "email_submitted": bool(s.get("email_status")),
    }


# ── public / guest ─────────────────────────────────────────────────────────


def get_layout(event, params, body):
    slots = {s["slot_id"]: s for s in core.scan_all("slots")}
    return 200, {"slots": [
        {"slot_id": sid, "source": core.slot_source(sid), "status": slots.get(sid, {}).get("status", "UNKNOWN"),
         "updated_at": slots.get(sid, {}).get("updated_at", core.iso(core.now()))}
        for sid in core.SLOT_IDS
    ]}


def get_claim(event, params, body):
    return 200, _claim_view(_session_from_token(params["token"]))


def post_claim_email(event, params, body):
    s = _session_from_token(params["token"])
    email = (body.get("email") or "").strip()
    if body.get("consent_for_this_session") is not True or not EMAIL_RE.match(email) or len(email) > 254:
        raise BusinessError(400, "INVALID_INPUT", "Email không hợp lệ hoặc chưa đồng ý nhận email")
    at = core.now()
    try:
        core.table("sessions").update_item(
            Key={"session_id": s["session_id"]},
            ConditionExpression="attribute_not_exists(email_status) AND claim_nonce = :n",
            UpdateExpression="SET email = :e, email_collected_at = :at, email_status = :q",
            ExpressionAttributeValues={":e": email, ":at": core.iso(at), ":q": "QUEUED", ":n": s["claim_nonce"]},
        )
    except Exception as err:  # noqa: BLE001
        if core.is_conditional_failure(err):
            raise BusinessError(409, "EMAIL_ALREADY_SENT", "Phiên này đã gửi email") from err
        raise
    try:
        message_id = services.send_guide_email(email, s)
        status, extra = "ACCEPTED_BY_SES", {":m": message_id or "-"}
        expr = "SET email_status = :st, ses_message_id = :m"
    except Exception as err:  # noqa: BLE001 — SES lỗi không rollback phiên (SIM-14)
        core.log.warning("SES lỗi: %s", type(err).__name__)
        status, extra, expr = "FAILED", {":r": type(err).__name__}, "SET email_status = :st, email_error = :r"
        core.alert("EMAIL_FAILED", f"Không gửi được email cho lượt {s['session_ref']} ({type(err).__name__})",
                   session_id=s["session_id"])
    core.table("sessions").update_item(Key={"session_id": s["session_id"]}, UpdateExpression=expr,
                                       ExpressionAttributeValues={":st": status, **extra})
    return 202, {"email_status": "QUEUED"}


# ── kiosk ──────────────────────────────────────────────────────────────────


def get_active_claims(event, params, body):
    require(event, "KIOSK", "ADMIN")
    sessions = core.scan_all("sessions", FilterExpression="#s IN (:r, :p) AND attribute_exists(claim_nonce)",
                             ExpressionAttributeNames={"#s": "state"},
                             ExpressionAttributeValues={":r": "RESERVED", ":p": "PARKED"})
    live = sorted((s for s in sessions if _claim_live(s)), key=lambda s: s["checkin_at"], reverse=True)
    return 200, [{
        "session_ref": s["session_ref"], "slot_id": s["slot_id"], "claim_url": services.claim_url(s),
        "claim_expires_at": s["claim_expires_at"], "route_steps": core.route_steps(s["slot_id"]),
        "checkin_at": s["checkin_at"],
    } for s in live]


# ── admin ──────────────────────────────────────────────────────────────────


def _alerts(limit=30):
    items = core.scan_all("alerts", FilterExpression="acked = :f", ExpressionAttributeValues={":f": False})
    return sorted((core.plain(a) for a in items), key=lambda a: a["created_at"], reverse=True)[:limit]


def _devices():
    stored = {d["device_id"]: core.plain(d) for d in core.scan_all("devices")}
    out = []
    for device_id in core.DEVICES:
        d = stored.get(device_id, {})
        online = services.device_online(device_id)
        out.append({
            "device_id": device_id,
            "state": ("ONLINE" if d.get("state") != "DEGRADED" else "DEGRADED") if online else "OFFLINE",
            "last_seen_at": d.get("last_seen_at"),
            "firmware_version": d.get("firmware_version"),
            "gates": d.get("gates"),
            "display": d.get("display"),
            "pending_commands": len(d.get("pending_commands") or {}),
        })
    return out


def get_dashboard(event, params, body):
    require(event, "ADMIN")
    slots = core.scan_all("slots")
    count = lambda st: sum(1 for s in slots if s.get("status") == st)  # noqa: E731
    return 200, {
        "available": count("AVAILABLE"), "reserved": count("RESERVED"), "occupied": count("OCCUPIED"),
        "unknown": count("UNKNOWN") + (len(core.SLOT_IDS) - len(slots)), "out_of_service": count("OUT_OF_SERVICE"),
        "offline_devices": [d["device_id"] for d in _devices() if d["state"] == "OFFLINE"],
        "alerts": _alerts(),
    }


def list_sessions(event, params, body):
    require(event, "ADMIN")
    qs = event.get("queryStringParameters") or {}
    status = qs.get("status")
    kwargs = {}
    if status == "OPEN":
        kwargs = {"FilterExpression": "#s IN (" + ", ".join(f":s{i}" for i in range(len(core.OPEN_STATES))) + ")",
                  "ExpressionAttributeNames": {"#s": "state"},
                  "ExpressionAttributeValues": {f":s{i}": st for i, st in enumerate(core.OPEN_STATES)}}
    elif status:
        kwargs = {"FilterExpression": "#s = :s", "ExpressionAttributeNames": {"#s": "state"},
                  "ExpressionAttributeValues": {":s": status}}
    items = sorted(core.scan_all("sessions", **kwargs), key=lambda s: s["session_id"], reverse=True)
    limit = min(int(qs.get("limit", 50)), 200)
    return 200, {"items": [admin_session_view(s) for s in items[:limit]], "total": len(items)}


def get_session(event, params, body):
    require(event, "ADMIN")
    return 200, admin_session_view(logic.get_session(params["id"]))


def resolve_plate(event, params, body):
    actor = require(event, "ADMIN")
    return 200, admin_session_view(logic.resolve_review(params["id"], body, actor))


def renew_claim(event, params, body):
    actor = require(event, "ADMIN")
    return 200, admin_session_view(logic.renew_claim(params["id"], actor))


def payment(event, params, body):
    actor = require(event, "ADMIN")
    s = logic.record_payment(params["id"], body.get("payment_status"), body.get("amount_vnd"), body.get("note"), actor)
    return 200, admin_session_view(s)


def open_exit(event, params, body):
    actor = require(event, "ADMIN")
    return 200, admin_session_view(logic.open_exit(params["id"], actor))


def confirm_passage(event, params, body):
    actor = require(event, "ADMIN")
    return 200, admin_session_view(logic.confirm_passage(params["id"], actor))


def get_devices(event, params, body):
    require(event, "ADMIN")
    return 200, _devices()


def get_pricing(event, params, body):
    require(event, "ADMIN")
    return 200, services.current_pricing()


def put_pricing(event, params, body):
    actor = require(event, "ADMIN")
    try:
        new = {k: int(body[k]) for k in ("free_minutes", "first_hour_vnd", "next_hour_vnd")}
    except (KeyError, TypeError, ValueError) as err:
        raise BusinessError(400, "INVALID_INPUT", "Cần free_minutes, first_hour_vnd, next_hour_vnd là số nguyên") from err
    if any(v < 0 for v in new.values()) or new["free_minutes"] > 60:
        raise BusinessError(400, "INVALID_INPUT", "Giá trị không hợp lệ")
    cur = services.current_pricing()
    item = {"config_id": "current", "version": int(cur.get("version", 0)) + 1, **new,
            "updated_at": core.iso(core.now()), "updated_by": actor}
    core.table("pricing").put_item(Item=item)
    return 200, item


def gate_manual(event, params, body):
    """Điều khiển tay một cần (thử cơ cấu/demo). Có ghi cảnh báo để lưu vết."""
    actor = require(event, "ADMIN")
    gate, action = params["gate"].upper(), (body.get("action") or "").upper()
    if gate not in ("ENTRY", "EXIT") or action not in ("OPEN", "CLOSE"):
        raise BusinessError(400, "INVALID_INPUT", "gate ENTRY|EXIT, action OPEN|CLOSE")
    if not services.device_online(core.GATE_ID):
        raise BusinessError(503, "DEVICE_OFFLINE", "ESP cổng đang offline")
    cmd = services.gate_command(gate, action)
    core.alert("MANUAL_GATE", f"{actor} điều khiển tay cần {gate}: {action}", level="INFO")
    return 202, {"command_id": cmd["command_id"]}


def ack_alert(event, params, body):
    require(event, "ADMIN")
    core.table("alerts").update_item(Key={"alert_id": params["id"]}, UpdateExpression="SET acked = :t",
                                     ExpressionAttributeValues={":t": True})
    return 200, {"ok": True}


ROUTES = {
    "GET /v1/public/layout": get_layout,
    "GET /v1/public/claims/{token}": get_claim,
    "POST /v1/public/claims/{token}/email": post_claim_email,
    "GET /v1/kiosk/active-claims": get_active_claims,
    "GET /v1/admin/dashboard": get_dashboard,
    "GET /v1/admin/sessions": list_sessions,
    "GET /v1/admin/sessions/{id}": get_session,
    "POST /v1/admin/sessions/{id}/resolve-plate": resolve_plate,
    "POST /v1/admin/sessions/{id}/renew-claim": renew_claim,
    "POST /v1/admin/sessions/{id}/payment": payment,
    "POST /v1/admin/sessions/{id}/open-exit": open_exit,
    "POST /v1/admin/sessions/{id}/confirm-passage": confirm_passage,
    "GET /v1/admin/devices": get_devices,
    "GET /v1/admin/pricing": get_pricing,
    "PUT /v1/admin/pricing": put_pricing,
    "POST /v1/admin/gates/{gate}/command": gate_manual,
    "POST /v1/admin/alerts/{id}/ack": ack_alert,
}


def _idempotent(event, route, fn, params, body):
    """Mutation có Idempotency-Key: trả lại đúng kết quả cũ khi client retry."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    key = headers.get("idempotency-key")
    if event.get("requestContext", {}).get("http", {}).get("method") == "GET" or not key:
        return fn(event, params, body)
    record_id = f"idem#{route}#{params.get('id') or params.get('token', '')[:40]}#{key[:80]}"
    saved = core.table("processed").get_item(Key={"message_id": record_id}).get("Item")
    if saved:
        return int(saved["status"]), json.loads(saved["body"])
    status, result = fn(event, params, body)
    item = core.processed_item(record_id, "idempotency")
    item.update({"status": status, "body": core.dumps(result)})
    core.table("processed").put_item(Item=item)
    return status, result


def handler(event, _context):
    request_id = event.get("requestContext", {}).get("requestId", "-")
    route = event.get("routeKey", "")
    fn = ROUTES.get(route)
    if not fn:
        return respond(404, {"code": "NOT_FOUND", "message": "Không có endpoint"}, request_id)
    try:
        raw = event.get("body") or ""
        if raw and event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return respond(400, {"code": "INVALID_INPUT", "message": "Body phải là JSON object"}, request_id)
    try:
        status, result = _idempotent(event, route, fn, event.get("pathParameters") or {}, body)
        return respond(status, result, request_id)
    except BusinessError as err:
        return respond(err.status, {"code": err.code, "message": err.message}, request_id)
    except Exception:  # noqa: BLE001
        core.log.exception("lỗi xử lý %s", route)
        return respond(500, {"code": "INTERNAL", "message": "Lỗi máy chủ"}, request_id)
