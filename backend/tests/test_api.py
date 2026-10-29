"""HTTP API v1: event giống payload 2.0 của API Gateway HTTP API."""
import json

from parking import api, ingest

from conftest import session_of, slot_changed, slot_of, snapshot, vehicle

KEY_HEADER = {"Idempotency-Key": "8f3c1d2e-key-0001"}


def call(app, method, path, body=None, headers=None, groups=None):
    ctx = {"http": {"method": method}, "stage": "v1", "requestId": "req-1"}
    if groups is not None:
        ctx["authorizer"] = {"jwt": {"claims": {"cognito:groups": groups}}}
    event = {"rawPath": f"/v1{path}", "headers": headers or {}, "requestContext": ctx,
             "body": json.dumps(body) if isinstance(body, dict) else body, "isBase64Encoded": False}
    response = api.handle(app, event)
    return response["statusCode"], json.loads(response["body"])


def entered(app, plate="51A-12345"):
    """Xe vào và trả token QR lấy từ kiosk, như khách quét QR."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app, plate=plate))
    status, claims = call(app, "GET", "/kiosk/active-claims", groups="[KIOSK]")
    assert status == 200
    return claims[0]["claim_url"].rsplit("/s/", 1)[1]


def test_layout_reports_unknown_until_snapshot(app):
    status, body = call(app, "GET", "/public/layout")
    assert status == 200 and {s["status"] for s in body["slots"]} == {"UNKNOWN"}
    ingest.process(app, snapshot(app, occupied={"F1-A2"}))
    ingest.process(app, vehicle(app))
    slots = {s["slot_id"]: s for s in call(app, "GET", "/public/layout")[1]["slots"]}
    assert (slots["F1-A1"]["status"], slots["F1-A1"]["source"]) == ("RESERVED", "SENSOR")
    assert slots["F1-A2"]["status"] == "OCCUPIED" and slots["F1-A3"]["status"] == "AVAILABLE"
    assert "plate" not in json.dumps(slots)


def test_claim_page_shows_route_without_identity(app):
    token = entered(app)
    status, claim = call(app, "GET", f"/public/claims/{token}")
    assert status == 200
    assert claim["slot_id"] == "F1-A1" and claim["route_steps"][0] == "Tầng 1"
    assert not claim["email_submitted"] and "51A" not in json.dumps(claim)


def test_email_sent_once_per_session(app):
    """SIM-03: một email; retry cùng key trả 202 không gửi lại; key khác → 409."""
    token = entered(app)
    body = {"email": "visitor@example.com", "consent_for_this_session": True}
    assert call(app, "POST", f"/public/claims/{token}/email", body, KEY_HEADER) == (202, {"email_status": "QUEUED"})
    assert call(app, "POST", f"/public/claims/{token}/email", body, KEY_HEADER)[0] == 202
    status, error = call(app, "POST", f"/public/claims/{token}/email", body, {"Idempotency-Key": "another-key-02"})
    assert (status, error["code"]) == (409, "EMAIL_ALREADY_SENT")
    assert len(app.mailer.sent) == 1 and "F1-A1" in app.mailer.sent[0][2]
    session = session_of(app, slot_of(app, "F1-A1")["reserved_session_id"])
    assert session["email_status"] == "ACCEPTED_BY_SES"
    assert call(app, "GET", f"/public/claims/{token}")[1]["email_submitted"] is True


def test_email_rejects_bad_input(app):
    token = entered(app)
    for body in ({"email": "khong-phai-email", "consent_for_this_session": True},
                 {"email": "visitor@example.com", "consent_for_this_session": "true"}):
        status, error = call(app, "POST", f"/public/claims/{token}/email", body, KEY_HEADER)
        assert (status, error["code"]) == (400, "INVALID_INPUT")
    status, error = call(app, "POST", f"/public/claims/{token}/email",
                         {"email": "visitor@example.com", "consent_for_this_session": True})
    assert (status, error["code"]) == (400, "INVALID_INPUT")  # thiếu Idempotency-Key
    assert not app.mailer.sent


def test_ses_failure_keeps_session(app):
    """SIM-14: SES lỗi → khách vẫn nhận 202 và lộ trình, quản trị thấy FAILED."""
    token = entered(app)
    app.mailer.fail = True
    body = {"email": "visitor@example.com", "consent_for_this_session": True}
    assert call(app, "POST", f"/public/claims/{token}/email", body, KEY_HEADER)[0] == 202
    session = session_of(app, slot_of(app, "F1-A1")["reserved_session_id"])
    assert (session["state"], session["email_status"]) == ("RESERVED", "FAILED")


def test_expired_or_forged_token(app):
    """SIM-15: hết 15 phút → 410; token bị sửa → 404."""
    token = entered(app)
    forged = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert call(app, "GET", f"/public/claims/{forged}")[1]["code"] == "NOT_FOUND"
    app.clock.advance(minutes=15)
    status, error = call(app, "GET", f"/public/claims/{token}")
    assert (status, error["code"]) == (410, "TOKEN_EXPIRED")
    body = {"email": "visitor@example.com", "consent_for_this_session": True}
    assert call(app, "POST", f"/public/claims/{token}/email", body, KEY_HEADER)[0] == 410


def test_kiosk_and_admin_require_groups(app):
    assert call(app, "GET", "/kiosk/active-claims")[1]["code"] == "UNAUTHENTICATED"
    assert call(app, "GET", "/admin/dashboard", groups="[KIOSK]")[1]["code"] == "FORBIDDEN"
    assert call(app, "GET", "/kiosk/active-claims", groups="[ADMIN KIOSK]")[0] == 200


def test_kiosk_lists_newest_claim_first(app):
    entered(app)
    app.clock.advance(seconds=10)
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app, plate="30F-67890"))
    claims = call(app, "GET", "/kiosk/active-claims", groups="[KIOSK]")[1]
    assert [c["slot_id"] for c in claims] == ["F1-A2", "F1-A1"]
    assert claims[0]["claim_url"].startswith("https://web.test/s/") and claims[0]["route_steps"]


def test_dashboard_counts_and_alerts(app):
    entered(app)
    ingest.process(app, slot_changed(app, "F2-C3", True))
    ingest.process(app, vehicle(app, confidence=0.3, plate="30F-67890"))
    status, board = call(app, "GET", "/admin/dashboard", groups="[ADMIN]")
    assert status == 200
    assert (board["available"], board["reserved"], board["occupied"], board["unknown"]) == (16, 1, 1, 0)
    assert set(board["offline_devices"]) == {"pi-01", "gate-01"}
    assert "Ô F2-C3 có xe nhưng không có phiên được gán" in board["alerts"]
    assert "1 lượt chờ quản trị xử lý" in board["alerts"]
    assert not any("51A" in a or "30F" in a for a in board["alerts"])


def test_unknown_route_and_internal_error_use_error_body(app, monkeypatch):
    status, error = call(app, "GET", "/nope")
    assert (status, error["code"]) == (404, "NOT_FOUND")
    monkeypatch.setattr(app.db, "batch_get", lambda *a: 1 / 0)
    status, error = call(app, "GET", "/public/layout")
    assert (status, error["code"], error["request_id"]) == (500, "INTERNAL_ERROR", "req-1")
