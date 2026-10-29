"""Endpoint quản trị: xử lý OCR, cấp lại QR, thu phí, mở cần ra, xác nhận xe qua, thiết bị, bảng giá."""
from parking import ingest

from conftest import device_status, gate_ack, session_of, slot_changed, slot_of, snapshot, vehicle
from test_api import call, entered


def admin(app, method, path, body=None, n=1, query=None, groups="[ADMIN]"):
    return call(app, method, path, body, {"Idempotency-Key": f"admin-key-{n:04d}"}, groups, query)


def parked_then_exit(app, plate="51A-12345", minutes=61, exit_confidence=0.93):
    """Xe vào, đỗ F1-A1, sau `minutes` phút đến cổng ra với gate-01 online. Trả session_id."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app, plate=plate))
    session_id = slot_of(app, "F1-A1")["reserved_session_id"]
    ingest.process(app, slot_changed(app, "F1-A1", True))
    app.clock.advance(minutes=minutes)
    ingest.process(app, snapshot(app, occupied={"F1-A1"}))
    ingest.process(app, device_status(app, "gate-01"))
    ingest.process(app, vehicle(app, lane="EXIT", color="RED", plate=plate, confidence=exit_confidence))
    return session_id


def review_ids(app):
    return [s["session_id"] for s in admin(app, "GET", "/admin/sessions", query={"status": "MANUAL_REVIEW"})[1]["sessions"]]


def test_exit_journey_payment_open_and_confirm(app):
    """SIM-07: phí dự kiến → thu tiền → chỉ cần ra mở → xác nhận qua cổng mới đóng phiên."""
    sid = parked_then_exit(app)
    base = f"/admin/sessions/{sid}"
    assert admin(app, "POST", f"{base}/open-exit", n=1)[1]["code"] == "INVALID_STATE"
    wrong = admin(app, "POST", f"{base}/payment", {"payment_status": "PAID_CASH", "amount_vnd": 10000}, n=2)
    assert wrong[0] == 409
    status, paid = admin(app, "POST", f"{base}/payment",
                         {"payment_status": "PAID_CASH", "amount_vnd": 15000, "note": "Đã thu tại cổng"}, n=3)
    assert status == 200 and (paid["state"], paid["payment_status"], paid["paid_amount_vnd"]) == \
        ("EXIT_REQUESTED", "PAID_CASH", 15000)
    assert paid["audit"][-1]["actor_id"] == "admin-sub-1"

    status, opened = admin(app, "POST", f"{base}/open-exit", n=4)
    assert status == 202
    gates = app.publisher.of_type("gate_command")
    assert (gates[-1]["gate"], gates[-1]["command_id"]) == ("EXIT", opened["command_id"])
    assert admin(app, "POST", f"{base}/open-exit", n=4)[1]["command_id"] == opened["command_id"]
    assert len(app.publisher.of_type("gate_command")) == len(gates)  # cùng key: không mở lần hai

    ingest.process(app, gate_ack(app, opened["command_id"], gate="EXIT"))
    assert session_of(app, sid)["state"] == "EXIT_GATE_OPEN"
    status, closed = admin(app, "POST", f"{base}/confirm-passage", n=5)
    assert status == 200 and closed["state"] == "CLOSED" and closed["exit_confirmed_at"]
    assert app.db.get(app.cfg.tables.active_plates, {"plate_normalized": "51A-12345"}) is None
    assert "reserved_session_id" not in slot_of(app, "F1-A1")

    layout = {s["slot_id"]: s["status"] for s in call(app, "GET", "/public/layout")[1]["slots"]}
    assert layout["F1-A1"] == "OCCUPIED"  # ô chỉ trống khi cảm biến báo
    ingest.process(app, slot_changed(app, "F1-A1", False))
    assert ingest.process(app, vehicle(app)) == "RESERVED:F1-A1"  # cùng biển số vào lại được


def test_free_session_opens_without_payment_but_needs_online_gate(app):
    sid = parked_then_exit(app, minutes=5)
    assert session_of(app, sid)["payment_status"] == "NO_CHARGE"
    app.clock.advance(seconds=91)
    status, error = admin(app, "POST", f"/admin/sessions/{sid}/open-exit")
    assert (status, error["code"]) == (503, "DEVICE_OFFLINE")
    ingest.process(app, device_status(app, "gate-01"))
    assert admin(app, "POST", f"/admin/sessions/{sid}/open-exit")[0] == 202


def test_failed_publish_lets_same_key_retry(app, monkeypatch):
    sid = parked_then_exit(app, minutes=5)

    def broken(topic, payload):
        raise ConnectionError("IoT")

    real = app.publisher.publish
    monkeypatch.setattr(app.publisher, "publish", broken)
    assert admin(app, "POST", f"/admin/sessions/{sid}/open-exit", n=7)[1]["code"] == "DEVICE_OFFLINE"
    monkeypatch.setattr(app.publisher, "publish", real)
    assert admin(app, "POST", f"/admin/sessions/{sid}/open-exit", n=7)[0] == 202
    assert len(app.publisher.of_type("gate_command")) == 2  # lệnh vào + lệnh ra


def test_resolve_low_confidence_entry(app):
    ingest.process(app, snapshot(app))
    assert ingest.process(app, vehicle(app, confidence=0.4)) == "MANUAL_REVIEW:LOW_CONFIDENCE"
    [review_id] = review_ids(app)
    body = {"action": "ENTRY", "plate_text": "51a 12345", "reason": "OCR đọc thiếu nét"}
    status, result = admin(app, "POST", f"/admin/sessions/{review_id}/resolve-plate", body, n=1)
    assert status == 200 and result["commands_sent"]
    assert (result["review"]["state"], result["session"]["state"], result["session"]["slot_id"]) == \
        ("RESOLVED", "RESERVED", "F1-A1")
    assert result["session"]["plate_normalized"] == "51A-12345"
    assert result["session"]["resolved_from_session_id"] == review_id
    assert app.publisher.of_type("gate_command")[-1]["gate"] == "ENTRY"

    replay = admin(app, "POST", f"/admin/sessions/{review_id}/resolve-plate", body, n=1)[1]
    assert replay["session"]["session_id"] == result["session"]["session_id"]
    assert len(app.publisher.of_type("gate_command")) == 1
    assert admin(app, "POST", f"/admin/sessions/{review_id}/resolve-plate", body, n=2)[0] == 409
    assert review_ids(app) == []


def test_resolve_exit_locks_fee_when_car_arrived(app):
    """Phí tính đến lúc xe tới cổng ra (50 phút), không tính thời gian quản trị xử lý."""
    sid = parked_then_exit(app, minutes=50, exit_confidence=0.4)
    [review_id] = review_ids(app)
    app.clock.advance(minutes=30)
    body = {"action": "EXIT", "plate_text": "51A-12345", "reason": "Biển số bị che một phần"}
    status, result = admin(app, "POST", f"/admin/sessions/{review_id}/resolve-plate", body)
    assert status == 200 and result["session"]["session_id"] == sid
    assert (result["session"]["state"], result["session"]["fee_vnd"]) == ("PAYMENT_PENDING", 10000)


def test_resolve_validation_and_dismiss(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app, color="RED"))
    [review_id] = review_ids(app)
    path = f"/admin/sessions/{review_id}/resolve-plate"
    assert admin(app, "POST", path, {"action": "ENTRY", "plate_text": "51A-12345"})[0] == 400  # thiếu lý do
    assert admin(app, "POST", path, {"action": "ENTRY", "plate_text": "ABC", "reason": "x"})[0] == 400
    status, result = admin(app, "POST", path, {"action": "DISMISS", "reason": "Thẻ sai làn, khách quay đầu"})
    assert status == 200 and result["review"]["state"] == "DISMISSED" and result["session"] is None


def test_renew_claim_invalidates_old_qr(app):
    token = entered(app)
    sid = slot_of(app, "F1-A1")["reserved_session_id"]
    status, claim = admin(app, "POST", f"/admin/sessions/{sid}/renew-claim", n=1)
    new_token = claim["claim_url"].rsplit("/s/", 1)[1]
    assert status == 200 and new_token != token
    assert call(app, "GET", f"/public/claims/{token}")[1]["code"] == "TOKEN_EXPIRED"
    assert call(app, "GET", f"/public/claims/{new_token}")[0] == 200
    assert admin(app, "POST", f"/admin/sessions/{sid}/renew-claim", n=1)[1]["claim_url"] == claim["claim_url"]


def test_session_list_filter_pagination_and_identity_expiry(app):
    ingest.process(app, snapshot(app))
    for plate in ("51A-11111", "51A-22222", "51A-33333"):
        ingest.process(app, vehicle(app, plate=plate))
        app.clock.advance(seconds=1)
    status, first = admin(app, "GET", "/admin/sessions", query={"limit": "2"})
    assert status == 200 and [s["plate_normalized"] for s in first["sessions"]] == ["51A-33333", "51A-22222"]
    second = admin(app, "GET", "/admin/sessions", query={"limit": "2", "cursor": first["next_cursor"]})[1]
    assert [s["plate_normalized"] for s in second["sessions"]] == ["51A-11111"]
    assert len(admin(app, "GET", "/admin/sessions", query={"status": "RESERVED"})[1]["sessions"]) == 3
    assert admin(app, "GET", "/admin/sessions", query={"status": "NOPE"})[0] == 400
    assert admin(app, "GET", "/admin/sessions", query={"cursor": "%%%"})[0] == 400

    sid = first["sessions"][0]["session_id"]
    assert admin(app, "GET", f"/admin/sessions/{sid}")[1]["plate_normalized"] == "51A-33333"
    app.clock.advance(days=10)
    assert admin(app, "GET", f"/admin/sessions/{sid}")[1]["plate_normalized"] is None  # quá hạn 10 ngày (SIM-16)
    assert admin(app, "GET", "/admin/sessions/01ARZ3NDEKTSV4RRFFQ69G5FAV")[0] == 404


def test_devices_view(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, device_status(app, "gate-01"))
    ingest.process(app, gate_ack(app, None, gate="EXIT", state="ERROR", error_code="MOTOR_TIMEOUT"))
    devices = {d["device_id"]: d for d in admin(app, "GET", "/admin/devices")[1]["devices"]}
    assert (devices["pi-01"]["online"], devices["gate-01"]["online"], devices["slots-01"]["online"]) == \
        (False, True, True)
    assert devices["gate-01"]["gates"]["EXIT"] == {"state": "ERROR", "error_code": "MOTOR_TIMEOUT",
                                                   "updated_at": devices["gate-01"]["last_seen_at"]}
    assert devices["slots-01"]["snapshot_fresh"] is True


def test_pricing_change_applies_to_new_sessions_only(app):
    assert admin(app, "GET", "/admin/pricing")[1]["version"] == 1
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    old_sid = slot_of(app, "F1-A1")["reserved_session_id"]
    rules = {"free_minutes": 10, "first_block_minutes": 60, "first_block_vnd": 20000, "extra_hour_vnd": 8000}
    status, pricing = admin(app, "PUT", "/admin/pricing", {**rules, "reason": "Giá cuối tuần"}, n=1)
    assert status == 200 and pricing["version"] == 2 and pricing["updated_by"] == "admin-sub-1"
    assert admin(app, "PUT", "/admin/pricing", rules, n=1)[1]["version"] == 2  # cùng key không tăng version
    assert admin(app, "PUT", "/admin/pricing", {**rules, "free_minutes": 120}, n=2)[0] == 400
    ingest.process(app, vehicle(app, plate="30F-67890"))
    new_sid = slot_of(app, "F1-A2")["reserved_session_id"]
    assert session_of(app, old_sid)["pricing"]["first_block_vnd"] == 10000
    assert session_of(app, new_sid)["pricing"]["first_block_vnd"] == 20000


def test_admin_mutations_need_admin_group_and_key(app):
    sid = parked_then_exit(app, minutes=5)
    assert admin(app, "POST", f"/admin/sessions/{sid}/open-exit", groups="[KIOSK]")[1]["code"] == "FORBIDDEN"
    status, error = call(app, "POST", f"/admin/sessions/{sid}/open-exit", groups="[ADMIN]")
    assert (status, error["code"]) == (400, "INVALID_INPUT")
    assert admin(app, "GET", "/admin/pricing", groups="[KIOSK]")[0] == 403
