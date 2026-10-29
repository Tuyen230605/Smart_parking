"""Job theo lịch: hết hạn giữ ô (SIM-13) và xóa dữ liệu định danh sau 10 ngày (SIM-16)."""
import pytest

from parking import ingest, jobs

from conftest import session_of, slot_changed, slot_of, snapshot, vehicle
from test_api import call, entered


def test_reservation_expires_after_five_minutes(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    sid = slot_of(app, "F1-A1")["reserved_session_id"]
    app.clock.advance(minutes=4)
    assert jobs.expire_reservations(app) == {"expired": 0, "skipped": 0}
    app.clock.advance(minutes=1, seconds=1)
    assert jobs.expire_reservations(app) == {"expired": 1, "skipped": 0}
    session = session_of(app, sid)
    assert session["state"] == "EXPIRED" and "claim_pk" not in session
    assert session["audit"][-1]["action"] == "expire-reservation"
    assert "reserved_session_id" not in slot_of(app, "F1-A1")
    assert app.db.get(app.cfg.tables.active_plates, {"plate_normalized": "51A-12345"}) is None
    assert jobs.expire_reservations(app) == {"expired": 0, "skipped": 0}  # chạy lại không đổi gì
    ingest.process(app, snapshot(app))
    assert ingest.process(app, vehicle(app)) == "RESERVED:F1-A1"  # ô và biển số dùng lại được


def test_occupied_slot_is_not_released(app):
    """Ô đã có xe thì không giải phóng dù phiên chưa kịp chuyển PARKED."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    sid = slot_of(app, "F1-A1")["reserved_session_id"]
    app.db.update(app.cfg.tables.slots, {"slot_id": "F1-A1"}, "SET occupied = :t", values={":t": True})
    app.clock.advance(minutes=6)
    assert jobs.expire_reservations(app) == {"expired": 0, "skipped": 1}
    assert session_of(app, sid)["state"] == "RESERVED"


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
