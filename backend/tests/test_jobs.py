"""Job theo lịch: hết hạn giữ ô (SIM-13), xóa dữ liệu định danh sau 10 ngày (SIM-16) và đếm thiết bị offline."""
import json

import pytest

from parking import ingest, jobs

from conftest import device_status, session_of, slot_changed, slot_of, snapshot, vehicle
from test_api import call, entered


def test_reservation_expires_after_five_minutes(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    sid = slot_of(app, "F1-A1")["reserved_session_id"]
    app.clock.advance(minutes=4)
    assert jobs.expire_reservations(app) == {"expired": 0, "parked": 0, "skipped": 0}
    app.clock.advance(minutes=1, seconds=1)
    assert jobs.expire_reservations(app) == {"expired": 1, "parked": 0, "skipped": 0}
    session = session_of(app, sid)
    assert session["state"] == "EXPIRED" and "claim_pk" not in session
    assert session["audit"][-1]["action"] == "expire-reservation"
    assert "reserved_session_id" not in slot_of(app, "F1-A1")
    assert app.db.get(app.cfg.tables.active_plates, {"plate_normalized": "51A-12345"}) is None
    assert jobs.expire_reservations(app) == {"expired": 0, "parked": 0, "skipped": 0}  # chạy lại không đổi gì
    ingest.process(app, snapshot(app))
    assert ingest.process(app, vehicle(app)) == "RESERVED:F1-A1"  # ô và biển số dùng lại được


def test_occupied_slot_reconciles_to_parked(app):
    """Codex #5: ô đã có xe mà phiên chưa PARKED (ingest lỗi giữa chừng) thì job sửa thành PARKED, không giải phóng."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    sid = slot_of(app, "F1-A1")["reserved_session_id"]
    app.db.update(app.cfg.tables.slots, {"slot_id": "F1-A1"}, "SET occupied = :t", values={":t": True})
    app.clock.advance(minutes=6)
    assert jobs.expire_reservations(app) == {"expired": 0, "parked": 1, "skipped": 0}
    assert session_of(app, sid)["state"] == "PARKED"
    assert slot_of(app, "F1-A1")["reserved_session_id"] == sid


def test_parked_session_never_expires(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    ingest.process(app, slot_changed(app, "F1-A1", True))
    app.clock.advance(hours=2)
    assert jobs.expire_reservations(app)["expired"] == 0


def test_purge_removes_identity_and_keeps_fee_data(app):
    token = entered(app)
    sid = slot_of(app, "F1-A1")["reserved_session_id"]
    call(app, "POST", f"/public/claims/{token}/email", {"email": "visitor@example.com", "consent_for_this_session": True},
         {"Idempotency-Key": "email-key-0001"})
    ingest.process(app, vehicle(app, plate="30F-67890", confidence=0.3))  # phiên chờ xử lý cũng có biển số
    app.clock.advance(days=9, hours=22)
    assert jobs.purge_identity(app) == {"purged": 0, "open_sessions": 0}

    board = call(app, "GET", "/admin/dashboard", groups="[ADMIN]")[1]
    assert any("sẽ bị xóa biển số trong 24 giờ" in a for a in board["alerts"])

    app.clock.advance(hours=1)
    assert jobs.purge_identity(app) == {"purged": 2, "open_sessions": 2}
    session = session_of(app, sid)
    for attr in ("plate_normalized", "email", "pii_pk", "claim_nonce"):
        assert attr not in session
    assert session["identity_purged_at"] and session["checkin_at"] and session["pricing"]
    assert app.db.get(app.cfg.tables.active_plates, {"plate_normalized": "51A-12345"}) is None
    assert jobs.purge_identity(app) == {"purged": 0, "open_sessions": 0}


def test_email_collected_after_purge_is_purged_later(app):
    """Codex #6: phiên mở quá 10 ngày đã bị xóa biển số, được cấp lại QR rồi khách nhập email: email vẫn phải bị xóa đúng hạn."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    sid = slot_of(app, "F1-A1")["reserved_session_id"]
    ingest.process(app, slot_changed(app, "F1-A1", True))
    app.clock.advance(days=10)
    jobs.purge_identity(app)
    claim = call(app, "POST", f"/admin/sessions/{sid}/renew-claim", None, {"Idempotency-Key": "renew-0001"}, "[ADMIN]")[1]
    token = claim["claim_url"].rsplit("/s/", 1)[1]
    status, _ = call(app, "POST", f"/public/claims/{token}/email",
                     {"email": "visitor@example.com", "consent_for_this_session": True}, {"Idempotency-Key": "email-0001"})
    assert status == 202 and session_of(app, sid)["email"] == "visitor@example.com"
    app.clock.advance(days=9, hours=22)
    assert jobs.purge_identity(app)["purged"] == 0
    app.clock.advance(hours=1)
    assert jobs.purge_identity(app) == {"purged": 1, "open_sessions": 1}
    assert "email" not in session_of(app, sid)


def test_unknown_job_is_rejected(monkeypatch):
    with pytest.raises(ValueError):
        jobs.handler({"job": "drop_tables"}, None)


def test_dashboard_reports_recent_expiry(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    app.clock.advance(minutes=6)
    jobs.expire_reservations(app)
    alerts = call(app, "GET", "/admin/dashboard", groups="[ADMIN]")[1]["alerts"]
    assert "1 lượt giữ ô hết hạn trong 1 giờ qua (xe không vào ô được gán)" in alerts


def test_check_devices_logs_offline_count_for_alarm(app, monkeypatch, capsys):
    """Metric filter OfflineDevicesMetric (template) đọc `offline` từ log job_done; đếm như dashboard."""
    monkeypatch.setattr(jobs, "get_app", lambda: app)
    assert jobs.check_devices(app) == {"offline": 3, "offline_devices": ["pi-01", "gate-01", "slots-01"]}
    ingest.process(app, device_status(app, "pi-01"))
    ingest.process(app, snapshot(app))
    capsys.readouterr()
    assert jobs.handler({"job": "check_devices"}, None) == {"offline": 1, "offline_devices": ["gate-01"]}
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (line["event"], line["job"], line["offline"]) == ("job_done", "check_devices", 1)

    ingest.process(app, device_status(app, "pi-01", state="OFFLINE"))  # Last Will
    assert jobs.check_devices(app)["offline_devices"] == ["pi-01", "gate-01"]
    app.clock.advance(seconds=91)
    assert jobs.check_devices(app)["offline"] == 3
