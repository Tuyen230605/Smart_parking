"""Kiểm thử nghiệp vụ đầu cuối với DynamoDB giả (moto), không cần AWS.

    pip install "moto[dynamodb]" boto3 pytest
    cd backend && python -m pytest -q
"""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.update({
    "AWS_DEFAULT_REGION": "ap-southeast-1", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
    "CLAIM_HMAC_SECRET": "x" * 48, "WEB_BASE_URL": "https://web.example", "SENDER_EMAIL": "noreply@example.com",
})

import api_handler  # noqa: E402
import core  # noqa: E402
import iot_handler  # noqa: E402
import jobs  # noqa: E402
import services  # noqa: E402

KEYS = {"slots": "slot_id", "sessions": "session_id", "plates": "plate_normalized", "processed": "message_id",
        "devices": "device_id", "pricing": "config_id", "alerts": "alert_id",
        "plate_emails": "plate_normalized"}


@pytest.fixture()
def env(monkeypatch):
    with mock_aws():
        core.ddb.cache_clear()
        core.table.cache_clear()
        res = boto3.resource("dynamodb")
        for name, key in KEYS.items():
            res.create_table(TableName=core.table_name(name), BillingMode="PAY_PER_REQUEST",
                             KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                             AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}])
        sent = []
        monkeypatch.setattr(services, "mqtt_publish", lambda topic, payload: sent.append((topic, payload)))
        emails = []
        monkeypatch.setattr(services, "send_guide_email", lambda to, s, slot=None, unsubscribe=None: emails.append((to, s["session_ref"], slot, unsubscribe)) or "mid-1")
        jobs.seed()
        yield {"sent": sent, "emails": emails}
        core.ddb.cache_clear()
        core.table.cache_clear()


SEQ = iter(range(1, 10**6))


def device_msg(device_id, topic_kind, leaf, message_type, **fields):
    return {"mqtt_topic": f"parking/v1/site-01/{topic_kind}/{device_id}/{leaf}", "schema_version": 1,
            "message_type": message_type, "event_id": core.new_uuid(), "device_id": device_id,
            "boot_id": "boot-1", "seq": next(SEQ), "occurred_at": core.iso(core.now()), **fields}


def status(device_id, state="ONLINE"):
    return iot_handler.handler(device_msg(device_id, "devices", "status", "device_status", state=state,
                                          firmware_version="test"), None)


def snapshot(occupied=()):
    slots = [{"slot_id": s, "occupied": s in occupied, "source": core.slot_source(s)} for s in core.SLOT_IDS]
    return iot_handler.handler(device_msg("slots-01", "slots", "state", "slots_snapshot", slots=slots), None)


def slot_changed(slot_id, occupied):
    return iot_handler.handler(device_msg("slots-01", "slots", "state", "slot_changed", slot_id=slot_id,
                                          occupied=occupied, source=core.slot_source(slot_id)), None)


def vehicle(lane, color, plate, conf=0.93, event_id=None):
    msg = device_msg("pi-01", "vision", "events", "vehicle_detected", lane_id=lane, card_color=color,
                     plate_text=plate, plate_confidence=conf)
    if event_id:
        msg["event_id"] = event_id
    return iot_handler.handler(msg, None)


def api(method, path, body=None, groups="[ADMIN]", headers=None, route=None, params=None, qs=None):
    event = {"routeKey": route or f"{method} {path}", "pathParameters": params or {}, "queryStringParameters": qs,
             "headers": headers or {}, "body": json.dumps(body) if body is not None else None,
             "requestContext": {"requestId": "r1", "http": {"method": method}}}
    if groups:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"cognito:groups": groups, "username": "admin"}}}
    res = api_handler.handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def online_all():
    for d in core.DEVICES:
        status(d)
    snapshot()


def session(sid):
    return core.table("sessions").get_item(Key={"session_id": sid})["Item"]


def slot(sid):
    return core.table("slots").get_item(Key={"slot_id": sid})["Item"]


def topics(env):
    return [t.split("/")[3] + ":" + p.get("gate", p.get("screen", "")) for t, p in env["sent"]]


# ── kịch bản ───────────────────────────────────────────────────────────────


def test_slots_unknown_until_snapshot(env):
    assert {s["status"] for s in core.scan_all("slots")} == {"UNKNOWN"}
    status("slots-01")
    snapshot(occupied={"F1-A2"})
    assert slot("F1-A1")["status"] == "AVAILABLE"
    assert slot("F1-A2")["status"] == "OCCUPIED"


def lot(env):
    """Danh sách xe mới nhất backend gửi cho Pi qua MQTT."""
    msgs = [p for t, p in env["sent"] if t.endswith("/vision/pi-01/lot")]
    return msgs[-1] if msgs else None


def allow(session_id, plate):
    return api("POST", None, route="POST /v1/admin/sessions/{id}/resolve-plate", params={"id": session_id},
               body={"action": "ENTRY", "plate_text": plate, "reason": "Cho vào"})


def test_entry_and_exit_need_admin(env):  # SIM-01, SIM-04, SIM-07 (miễn phí)
    online_all()
    r1 = vehicle("ENTRY", "GREEN", None, conf=0)  # Pi demo không đọc biển
    assert r1["result"] == "ENTRY_PENDING" and r1["plate"] == "11111"
    assert "gates:ENTRY" not in topics(env)  # chưa mở cần khi quản trị chưa cho vào
    r2 = vehicle("ENTRY", "GREEN", None, conf=0)
    assert r2["plate"] == "22222"
    assert lot(env)["pending_entry"] == ["11111", "22222"] and lot(env)["in_lot"] == []

    code, s1 = allow(r1["session_id"], "11111")
    assert code == 200 and s1["state"] == "PARKED" and "gates:ENTRY" in topics(env)
    assert lot(env)["in_lot"] == ["11111"]
    code, _ = api("POST", None, route="POST /v1/admin/sessions/{id}/resolve-plate", params={"id": r2["session_id"]},
                  body={"action": "REJECT", "reason": "nhầm"})
    assert code == 200
    r3 = vehicle("ENTRY", "GREEN", None, conf=0)
    assert r3["plate"] == "22222"  # số nhỏ nhất chưa dùng
    allow(r3["session_id"], "22222")
    assert lot(env)["in_lot"] == ["11111", "22222"]

    # Gợi ý ô (không gán): ô trống gần nhất lúc xem.
    code, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    assert code == 200 and claims[0]["slot_id"] == "F1-A1" and claims[0]["free_count"] == 18
    token = claims[0]["claim_url"].rsplit("/", 1)[1]
    slot_changed("F1-A1", True)
    code, claim = api("GET", None, route="GET /v1/public/claims/{token}", params={"token": token}, groups=None)
    assert code == 200 and claim["slot_id"] == "F1-A2" and "plate" not in json.dumps(claim)

    # Ra: xe số lớn nhất trước, chờ quản trị cho ra.
    env["sent"].clear()
    x = vehicle("EXIT", "RED", None, conf=0)
    s3 = session(r3["session_id"])
    assert x["fee_vnd"] == 0 and s3["state"] == "EXIT_REQUESTED" and s3["payment_status"] == "NO_CHARGE"
    assert "gates:EXIT" not in topics(env)
    assert lot(env)["pending_exit"] == ["22222"] and lot(env)["in_lot"] == ["11111", "22222"]
    code, s3 = api("POST", None, route="POST /v1/admin/sessions/{id}/open-exit", params={"id": r3["session_id"]})
    assert code == 200 and s3["state"] == "CLOSED" and "gates:EXIT" in topics(env)
    assert lot(env)["in_lot"] == ["11111"]
    assert "Item" not in core.table("plates").get_item(Key={"plate_normalized": "22222"})
    assert vehicle("EXIT", "RED", None, conf=0)["session_id"] == r1["session_id"]
    assert slot("F1-A1")["status"] == "OCCUPIED"  # cổng không đụng tới ô


def test_exit_with_empty_lot(env):
    online_all()
    assert vehicle("EXIT", "RED", None, conf=0)["result"] == "NO_CAR"


def test_paid_exit_requires_admin(env):  # SIM-07 có phí
    online_all()
    r = vehicle("ENTRY", "GREEN", "30F-67890")
    assert r["result"] == "ENTRY_PENDING" and r["plate"] == "30F-67890"  # biển đọc được thì giữ nguyên
    allow(r["session_id"], "30F-67890")
    core.table("sessions").update_item(
        Key={"session_id": r["session_id"]}, UpdateExpression="SET checkin_at = :c",
        ExpressionAttributeValues={":c": core.iso(core.now() - timedelta(minutes=61))})
    x = vehicle("EXIT", "RED", "30F-67890")
    assert x["fee_vnd"] == 15000 and session(r["session_id"])["state"] == "EXIT_REQUESTED"
    code, _ = api("POST", None, route="POST /v1/admin/sessions/{id}/open-exit", params={"id": r["session_id"]})
    assert code == 409  # chưa thu tiền
    code, _ = api("POST", None, route="POST /v1/admin/sessions/{id}/payment", params={"id": r["session_id"]},
                  body={"payment_status": "WAIVED"})
    assert code == 400  # WAIVED cần lý do
    code, s = api("POST", None, route="POST /v1/admin/sessions/{id}/payment", params={"id": r["session_id"]},
                  body={"payment_status": "PAID_CASH", "amount_vnd": 15000, "note": "Đã thu"})
    assert code == 200 and s["state"] == "CLOSED" and s["payment_status"] == "PAID_CASH"


def test_replay_and_full(env):  # SIM-10, SIM-06
    online_all()
    eid = core.new_uuid()
    r = vehicle("ENTRY", "GREEN", None, conf=0, event_id=eid)
    assert r["result"] == "ENTRY_PENDING"
    assert vehicle("ENTRY", "GREEN", None, conf=0, event_id=eid)["result"] == "DUPLICATE"
    assert len(core.scan_all("sessions")) == 1
    snapshot(occupied=set(core.SLOT_IDS))  # cả 18 ô báo có xe
    code, err = allow(r["session_id"], r["plate"])
    assert code == 409 and err["code"] == "SLOT_CONFLICT"
    assert "displays:LOT_FULL" in topics(env)


def test_wrong_lane_is_ignored(env):  # không còn hàng "chờ duyệt"
    online_all()
    assert vehicle("ENTRY", "RED", None, conf=0)["result"] == "IGNORED"
    assert vehicle("EXIT", "RED", "99Z-99999")["result"] == "NO_CAR"  # biển đọc được nhưng không có trong bãi
    assert core.scan_all("sessions") == []


def test_remember_email_for_plate(env):
    online_all()
    r = vehicle("ENTRY", "GREEN", None, conf=0)
    allow(r["session_id"], r["plate"])
    _, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    token = claims[0]["claim_url"].rsplit("/", 1)[1]
    route = "POST /v1/public/claims/{token}/email"
    code, _ = api("POST", None, route=route, params={"token": token}, groups=None,
                  body={"email": "khach@gmail.com", "consent_for_this_session": True, "remember": True})
    assert code == 202 and env["emails"][0][3]  # email có link hủy liên kết
    code, claim = api("GET", None, route="GET /v1/public/claims/{token}", params={"token": token}, groups=None)
    assert claim["linked_email"] == "kh***@gmail.com"

    # Lần sau: xe ra rồi vào lại, quản trị cho vào → tự gửi email, không cần quét QR.
    vehicle("EXIT", "RED", None, conf=0)
    api("POST", None, route="POST /v1/admin/sessions/{id}/open-exit", params={"id": r["session_id"]})
    again = vehicle("ENTRY", "GREEN", None, conf=0)
    assert again["plate"] == r["plate"]
    allow(again["session_id"], again["plate"])
    assert len(env["emails"]) == 2 and env["emails"][1][0] == "khach@gmail.com"
    assert session(again["session_id"])["email_auto"] is True

    # Hủy bằng link trong email → lần sau không gửi nữa.
    unsub = env["emails"][1][3].rsplit("/", 1)[1]
    code, _ = api("POST", None, route="POST /v1/public/unsubscribe/{token}", params={"token": unsub}, groups=None)
    assert code == 200 and core.scan_all("plate_emails") == []
    code, _ = api("POST", None, route="POST /v1/public/unsubscribe/{token}", params={"token": unsub[:-2] + "xx"},
                  groups=None)
    assert code == 404


def test_forget_email_from_qr_page(env):
    online_all()
    r = vehicle("ENTRY", "GREEN", None, conf=0)
    allow(r["session_id"], r["plate"])
    _, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    token = claims[0]["claim_url"].rsplit("/", 1)[1]
    api("POST", None, route="POST /v1/public/claims/{token}/email", params={"token": token}, groups=None,
        body={"email": "a@b.vn", "consent_for_this_session": True, "remember": True})
    code, body = api("POST", None, route="POST /v1/public/claims/{token}/forget-email", params={"token": token},
                     groups=None)
    assert code == 200 and core.scan_all("plate_emails") == []


def test_slots_offline_still_lets_cars_in(env):  # SIM-11: ô chỉ để chỉ đường
    online_all()
    core.table("devices").update_item(
        Key={"device_id": "slots-01"}, UpdateExpression="SET last_seen_at = :c",
        ExpressionAttributeValues={":c": core.iso(core.now() - timedelta(seconds=120))})
    out = jobs.monitor()
    assert "slots-01" in out["offline"]
    assert {s["status"] for s in core.scan_all("slots")} == {"UNKNOWN"}
    r = vehicle("ENTRY", "GREEN", None, conf=0)
    code, s = allow(r["session_id"], r["plate"])
    assert code == 200 and s["state"] == "PARKED"
    _, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    assert claims[0]["slot_id"] is None and claims[0]["route_steps"] == []


def test_email_once(env):  # SIM-03, SIM-15
    online_all()
    r = vehicle("ENTRY", "GREEN", None, conf=0)
    allow(r["session_id"], r["plate"])
    _, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    token = claims[0]["claim_url"].rsplit("/", 1)[1]
    route = "POST /v1/public/claims/{token}/email"
    body = {"email": "a@example.com", "consent_for_this_session": True, "slot_id": "F2-B3"}
    code, _ = api("POST", None, route=route, params={"token": token}, body={**body, "consent_for_this_session": False},
                  groups=None)
    assert code == 400
    code, res = api("POST", None, route=route, params={"token": token}, body=body, groups=None,
                    headers={"Idempotency-Key": "k1"})
    assert code == 202 and env["emails"][0][0] == "a@example.com" and env["emails"][0][2] == "F2-B3"
    code, _ = api("POST", None, route=route, params={"token": token}, body=body, groups=None,
                  headers={"Idempotency-Key": "k1"})
    assert code == 202 and len(env["emails"]) == 1  # retry cùng key
    code, err = api("POST", None, route=route, params={"token": token}, body=body, groups=None,
                    headers={"Idempotency-Key": "k2"})
    assert code == 409 and err["code"] == "EMAIL_ALREADY_SENT"
    code, err = api("GET", None, route="GET /v1/public/claims/{token}", params={"token": token[:-2] + "xx"}, groups=None)
    assert code == 404


def test_permissions(env):
    assert api("GET", "/v1/admin/dashboard", groups="[KIOSK]")[0] == 403
    assert api("GET", "/v1/admin/dashboard", groups=None)[0] == 401
    code, dash = api("GET", "/v1/admin/dashboard")
    assert code == 200 and dash["unknown"] == 18 and dash["lot"]["in_lot"] == []


def test_fee_table():
    p = services.DEFAULT_PRICING
    t0 = core.now()
    fee = lambda m: services.compute_fee(p, t0, t0 + timedelta(minutes=m))  # noqa: E731
    assert [fee(14), fee(15), fee(60), fee(61), fee(120), fee(121)] == [0, 10000, 10000, 15000, 15000, 20000]


def test_gate_ack_timeout(env):
    online_all()
    r = vehicle("ENTRY", "GREEN", None, conf=0)
    allow(r["session_id"], r["plate"])
    gate = core.table("devices").get_item(Key={"device_id": "gate-01"})["Item"]
    cmd_id, info = next(iter(gate["pending_commands"].items()))
    iot_handler.handler(device_msg("gate-01", "gates", "telemetry", "gate_telemetry", gate="ENTRY", state="OPEN",
                                   command_id=cmd_id, error_code=None), None)
    gate = core.table("devices").get_item(Key={"device_id": "gate-01"})["Item"]
    assert gate["pending_commands"] == {} and gate["gates"]["ENTRY"]["state"] == "OPEN"


def test_duplicate_plate(env):  # SIM-09
    online_all()
    a = vehicle("ENTRY", "GREEN", "51A-12345")
    assert allow(a["session_id"], "51A-12345")[0] == 200
    b = vehicle("ENTRY", "GREEN", "51A-12345")
    code, err = allow(b["session_id"], "51A-12345")
    assert code == 409 and err["code"] == "INVALID_STATE"  # biển đang có phiên trong bãi


def test_ses_failure_keeps_session(env, monkeypatch):  # SIM-14: SES lỗi vẫn chỉ đường, ghi FAILED
    online_all()
    r = vehicle("ENTRY", "GREEN", None, conf=0)
    allow(r["session_id"], r["plate"])
    _, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    token = claims[0]["claim_url"].rsplit("/", 1)[1]

    def ses_down(*_a, **_k):
        raise RuntimeError("MessageRejected: Email address is not verified")

    monkeypatch.setattr(services, "send_guide_email", ses_down)
    code, _ = api("POST", None, route="POST /v1/public/claims/{token}/email", params={"token": token}, groups=None,
                  body={"email": "chua-xac-minh@example.com", "consent_for_this_session": True})
    assert code == 202
    s = session(r["session_id"])
    assert s["email_status"] == "FAILED" and s["state"] == "PARKED"
    assert any(a["kind"] == "EMAIL_FAILED" for a in core.scan_all("alerts"))
    code, claim = api("GET", None, route="GET /v1/public/claims/{token}", params={"token": token}, groups=None)
    assert code == 200 and claim["slot_id"]  # vẫn xem được chỉ đường


def test_purge_after_ten_days(env):  # SIM-16: dữ liệu định danh quá hạn bị xóa
    online_all()
    r = vehicle("ENTRY", "GREEN", None, conf=0)
    allow(r["session_id"], r["plate"])
    old = core.iso(core.now() - timedelta(days=10))
    core.table("sessions").update_item(
        Key={"session_id": r["session_id"]},
        UpdateExpression="SET plate_collected_at = :o, created_at = :o, email = :e, email_collected_at = :o",
        ExpressionAttributeValues={":o": old, ":e": "a@b.vn"})
    assert jobs.handler({"job": "purge"}, None)["purged"] == 1
    s = session(r["session_id"])
    assert not {"plate_normalized", "plate_display", "email", "claim_nonce"} & s.keys()
    assert "identity_purged_at" in s
    assert core.scan_all("plates") == []  # biển số không còn bị khóa

