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
        "devices": "device_id", "pricing": "config_id", "alerts": "alert_id"}


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
        monkeypatch.setattr(services, "send_guide_email", lambda to, s: emails.append((to, s["slot_id"])) or "mid-1")
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


def test_full_entry_park_exit_free(env):  # SIM-01, SIM-04, SIM-07 (miễn phí)
    online_all()
    r = vehicle("ENTRY", "GREEN", "51A-12345")
    assert r["result"] == "RESERVED" and r["slot_id"] == "F1-A1"
    assert slot("F1-A1")["status"] == "RESERVED"
    assert "gates:ENTRY" in topics(env) and "displays:ENTRY_ROUTE" in topics(env)

    code, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    assert code == 200 and claims[0]["slot_id"] == "F1-A1"
    token = claims[0]["claim_url"].rsplit("/", 1)[1]
    code, claim = api("GET", None, route="GET /v1/public/claims/{token}", params={"token": token}, groups=None)
    assert code == 200 and claim["slot_id"] == "F1-A1" and "plate" not in json.dumps(claim)

    slot_changed("F1-A1", True)
    assert session(r["session_id"])["state"] == "PARKED"
    assert slot("F1-A1")["status"] == "OCCUPIED"

    env["sent"].clear()
    x = vehicle("EXIT", "RED", "51A12345")  # khác định dạng vẫn khớp
    assert x["fee_vnd"] == 0
    s = session(r["session_id"])
    assert s["state"] == "EXIT_OPENED" and s["payment_status"] == "NO_CHARGE"
    assert "gates:EXIT" in topics(env)

    code, body = api("POST", None, route="POST /v1/admin/sessions/{id}/confirm-passage", params={"id": r["session_id"]})
    assert code == 200 and body["state"] == "CLOSED"
    assert "Item" not in core.table("plates").get_item(Key={"plate_normalized": "51A12345"})
    slot_changed("F1-A1", False)
    assert slot("F1-A1")["status"] == "AVAILABLE"


def test_paid_exit_requires_admin(env):  # SIM-07 có phí
    online_all()
    r = vehicle("ENTRY", "GREEN", "30F-67890")
    core.table("sessions").update_item(
        Key={"session_id": r["session_id"]}, UpdateExpression="SET checkin_at = :c",
        ExpressionAttributeValues={":c": core.iso(core.now() - timedelta(minutes=61))})
    x = vehicle("EXIT", "RED", "30F-67890")
    assert x["fee_vnd"] == 15000
    assert session(r["session_id"])["state"] == "EXIT_REQUESTED"
    code, err = api("POST", None, route="POST /v1/admin/sessions/{id}/open-exit", params={"id": r["session_id"]})
    assert code == 409
    code, err = api("POST", None, route="POST /v1/admin/sessions/{id}/payment", params={"id": r["session_id"]},
                    body={"payment_status": "WAIVED"})
    assert code == 400  # WAIVED cần lý do
    code, s = api("POST", None, route="POST /v1/admin/sessions/{id}/payment", params={"id": r["session_id"]},
                  body={"payment_status": "PAID_CASH", "amount_vnd": 15000, "note": "Đã thu"})
    assert code == 200 and s["state"] == "EXIT_OPENED" and s["payment_status"] == "PAID_CASH"


def test_replay_and_full(env):  # SIM-10, SIM-06
    online_all()
    eid = core.new_uuid()
    assert vehicle("ENTRY", "GREEN", "51A-11111", event_id=eid)["result"] == "RESERVED"
    assert vehicle("ENTRY", "GREEN", "51A-11111", event_id=eid)["result"] == "DUPLICATE"
    assert len(core.scan_all("sessions")) == 1
    snapshot(occupied=set(core.SLOT_IDS) - {"F1-A1"})  # F1-A1 đang RESERVED, còn lại có xe
    assert vehicle("ENTRY", "GREEN", "51A-22222")["result"] == "LOT_FULL"
    assert "displays:LOT_FULL" in topics(env)


def test_manual_review_and_resolve(env):  # SIM-08
    online_all()
    r = vehicle("ENTRY", "GREEN", "51A-1Z345", conf=0.42)
    assert r["result"] == "MANUAL_REVIEW"
    assert not any(p.get("gate") for _, p in env["sent"])  # không mở cần tự động
    assert vehicle("ENTRY", "RED", "51A-99999")["result"] == "MANUAL_REVIEW"
    code, s = api("POST", None, route="POST /v1/admin/sessions/{id}/resolve-plate", params={"id": r["session_id"]},
                  body={"action": "ENTRY", "plate_text": "51A-12345", "reason": "OCR sai"})
    assert code == 200 and s["state"] == "RESERVED" and s["slot_id"] == "F1-A1" and s["plate_text"] == "51A-12345"


def test_slots_offline_and_reservation_expiry(env):  # SIM-11, SIM-13
    online_all()
    r = vehicle("ENTRY", "GREEN", "51A-12345")
    core.table("sessions").update_item(
        Key={"session_id": r["session_id"]}, UpdateExpression="SET reserved_at = :c",
        ExpressionAttributeValues={":c": core.iso(core.now() - timedelta(minutes=6))})
    core.table("devices").update_item(
        Key={"device_id": "slots-01"}, UpdateExpression="SET last_seen_at = :c",
        ExpressionAttributeValues={":c": core.iso(core.now() - timedelta(seconds=120))})
    out = jobs.monitor()
    assert "slots-01" in out["offline"] and out["expired"] == [r["session_id"]]
    assert {s["status"] for s in core.scan_all("slots")} == {"UNKNOWN"}
    assert "reserved_session_id" not in slot("F1-A1")
    assert vehicle("ENTRY", "GREEN", "51A-77777")["result"] == "LOT_FULL"  # không gán trên dữ liệu cũ
    status("slots-01")
    snapshot()
    assert slot("F1-A1")["status"] == "AVAILABLE"


def test_email_once(env):  # SIM-03, SIM-15
    online_all()
    vehicle("ENTRY", "GREEN", "51A-12345")
    _, claims = api("GET", "/v1/kiosk/active-claims", groups="[KIOSK]")
    token = claims[0]["claim_url"].rsplit("/", 1)[1]
    route = "POST /v1/public/claims/{token}/email"
    body = {"email": "a@example.com", "consent_for_this_session": True}
    code, _ = api("POST", None, route=route, params={"token": token}, body={**body, "consent_for_this_session": False},
                  groups=None)
    assert code == 400
    code, res = api("POST", None, route=route, params={"token": token}, body=body, groups=None,
                    headers={"Idempotency-Key": "k1"})
    assert code == 202 and env["emails"] == [("a@example.com", "F1-A1")]
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
    assert code == 200 and dash["unknown"] == 18


def test_fee_table():
    p = services.DEFAULT_PRICING
    t0 = core.now()
    fee = lambda m: services.compute_fee(p, t0, t0 + timedelta(minutes=m))  # noqa: E731
    assert [fee(14), fee(15), fee(60), fee(61), fee(120), fee(121)] == [0, 10000, 10000, 15000, 15000, 20000]


def test_gate_ack_timeout(env):
    online_all()
    vehicle("ENTRY", "GREEN", "51A-12345")
    gate = core.table("devices").get_item(Key={"device_id": "gate-01"})["Item"]
    cmd_id, info = next(iter(gate["pending_commands"].items()))
    iot_handler.handler(device_msg("gate-01", "gates", "telemetry", "gate_telemetry", gate="ENTRY", state="OPEN",
                                   command_id=cmd_id, error_code=None), None)
    gate = core.table("devices").get_item(Key={"device_id": "gate-01"})["Item"]
    assert gate["pending_commands"] == {} and gate["gates"]["ENTRY"]["state"] == "OPEN"


def test_slot_race_and_duplicate_plate(env, monkeypatch):  # SIM-09
    online_all()
    first = vehicle("ENTRY", "GREEN", "51A-12345")
    assert first["slot_id"] == "F1-A1"
    import logic
    # Giả lập hai Lambda đọc danh sách ô cùng lúc: cả hai thấy F1-A1 còn trống.
    monkeypatch.setattr(logic, "assignable_slots", lambda: ["F1-A1", "F1-A2"])
    second = vehicle("ENTRY", "GREEN", "51A-22222")
    assert second["result"] == "RESERVED" and second["slot_id"] == "F1-A2"
    again = vehicle("ENTRY", "GREEN", "51A-12345")
    assert again["result"] == "MANUAL_REVIEW"
    assert session(again["session_id"])["review_reason"] == "PLATE_ALREADY_ACTIVE"
