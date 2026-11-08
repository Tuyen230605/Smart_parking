"""Token QR, bảng giá, phát lệnh MQTT tới ESP gate và gửi email SES."""
import base64
import hashlib
import hmac
import json
import math
import os
from decimal import Decimal
from functools import lru_cache

import boto3

import core

# ── token QR: base64url(payload).base64url(HMAC-SHA256) ────────────────────


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret():
    secret = os.environ.get("CLAIM_HMAC_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("CLAIM_HMAC_SECRET chưa cấu hình hoặc quá ngắn")
    return secret.encode()


def make_token(session_id, nonce, expires_at):
    payload = _b64(json.dumps({"s": session_id, "n": nonce, "e": core.epoch(expires_at)}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token):
    """Trả dict {s, n, e} nếu chữ ký đúng, None nếu token giả/hỏng. Chưa kiểm tra hạn."""
    try:
        payload, sig = token.split(".")
        expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(payload))
        return data if {"s", "n", "e"} <= data.keys() else None
    except (ValueError, json.JSONDecodeError):
        return None


def claim_url(session):
    token = make_token(session["session_id"], session["claim_nonce"], core.parse_iso(session["claim_expires_at"]))
    return f"{os.environ.get('WEB_BASE_URL', 'http://localhost:5173').rstrip('/')}/s/{token}"


# ── bảng giá ───────────────────────────────────────────────────────────────
DEFAULT_PRICING = {
    "config_id": "current",
    "version": 1,
    "free_minutes": 15,
    "first_hour_vnd": 10000,
    "next_hour_vnd": 5000,
}


def current_pricing():
    item = core.table("pricing").get_item(Key={"config_id": "current"}).get("Item")
    return core.plain(item) if item else dict(DEFAULT_PRICING)


def compute_fee(pricing, checkin_at, end_at):
    """Miễn phí dưới free_minutes; đến 60 phút first_hour; mỗi giờ tiếp theo bắt đầu +next_hour."""
    seconds = max(0.0, (end_at - checkin_at).total_seconds())
    if seconds < int(pricing["free_minutes"]) * 60:
        return 0
    if seconds <= 3600:
        return int(pricing["first_hour_vnd"])
    extra_hours = math.ceil((seconds - 3600) / 3600)
    return int(pricing["first_hour_vnd"]) + extra_hours * int(pricing["next_hour_vnd"])


def format_vnd(amount):
    return f"{int(amount):,}".replace(",", ".")


# ── MQTT tới ESP gate (qua IoT Data Plane) ─────────────────────────────────


@lru_cache(maxsize=None)
def _iot():
    endpoint = os.environ["IOT_ENDPOINT"]
    return boto3.client("iot-data", endpoint_url=f"https://{endpoint}")


def mqtt_publish(topic, payload):
    """Điểm duy nhất publish ra IoT Core; test thay hàm này."""
    _iot().publish(topic=topic, qos=1, retain=False, payload=json.dumps(payload).encode())


def gate_command(gate, action, session_id=None):
    at = core.now()
    cmd = {
        "schema_version": 1,
        "message_type": "gate_command",
        "command_id": core.new_uuid(),
        "target_device_id": core.GATE_ID,
        "gate": gate,
        "action": action,
        "session_id": session_id,
        "issued_at": core.iso(at),
        "expires_at": core.iso(at + core.COMMAND_TTL),
    }
    mqtt_publish(f"parking/v1/{core.SITE_ID}/gates/{core.GATE_ID}/commands", cmd)
    # Ghi lệnh đang chờ ACK để job giám sát cảnh báo nếu servo không phản hồi.
    core.table("devices").update_item(
        Key={"device_id": core.GATE_ID},
        UpdateExpression="SET pending_commands = if_not_exists(pending_commands, :empty)",
        ExpressionAttributeValues={":empty": {}},
    )
    core.table("devices").update_item(
        Key={"device_id": core.GATE_ID},
        UpdateExpression="SET pending_commands.#c = :p",
        ExpressionAttributeNames={"#c": cmd["command_id"]},
        ExpressionAttributeValues={":p": {"gate": gate, "action": action, "issued_at": cmd["issued_at"]}},
    )
    core.log.info("gate_command %s %s %s", cmd["command_id"], gate, action)
    return cmd


def display_command(screen, lines, seconds=15):
    at = core.now()
    cmd = {
        "schema_version": 1,
        "message_type": "display_command",
        "command_id": core.new_uuid(),
        "target_device_id": core.GATE_ID,
        "screen": screen,
        "lines": [str(line)[:20] for line in lines[:3]],
        "issued_at": core.iso(at),
        "expires_at": core.iso(at + core.timedelta(seconds=seconds)),
    }
    mqtt_publish(f"parking/v1/{core.SITE_ID}/displays/{core.GATE_ID}/commands", cmd)
    return cmd


def device_online(device_id):
    item = core.table("devices").get_item(Key={"device_id": device_id}).get("Item")
    if not item or item.get("state") == "OFFLINE":
        return False
    seen = core.parse_iso(item.get("last_seen_at"))
    return bool(seen and core.now() - seen <= core.DEVICE_TIMEOUT)


# ── email SES ──────────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def _ses():
    return boto3.client("sesv2")


def send_guide_email(to_address, session):
    """Trả MessageId nếu SES chấp nhận. Không chứa biển số."""
    slot = session["slot_id"]
    steps = core.route_steps(slot)
    subject = f"Chỉ dẫn đỗ xe: ô {slot} (mã lượt {session['session_ref']})"
    text = "\n".join(
        [f"Xin chào,", "", f"Ô đỗ của bạn: {slot}", *[f"{i}. {s}" for i, s in enumerate(steps, 1)], "",
         f"Mã lượt: {session['session_ref']}",
         "Email này chỉ dùng cho lượt gửi xe hiện tại và được xóa sau tối đa 10 ngày."]
    )
    items = "".join(f"<li>{s}</li>" for s in steps)
    html = (
        f"<p>Xin chào,</p><p>Ô đỗ của bạn: <b style='font-size:20px'>{slot}</b></p>"
        f"<ol>{items}</ol><p>Mã lượt: <b>{session['session_ref']}</b></p>"
        "<p style='color:#666;font-size:12px'>Email này chỉ dùng cho lượt gửi xe hiện tại "
        "và được xóa sau tối đa 10 ngày.</p>"
    )
    res = _ses().send_email(
        FromEmailAddress=os.environ["SENDER_EMAIL"],
        Destination={"ToAddresses": [to_address]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": text, "Charset": "UTF-8"}, "Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    return res.get("MessageId")


def to_decimal(value):
    return Decimal(str(value))
