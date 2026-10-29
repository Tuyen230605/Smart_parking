"""Luồng thiết bị → backend theo các kịch bản SIM trong docs/simulation-and-test-plan.md."""
from parking import ingest
from parking.layout import SLOT_IDS
from parking.timeutil import iso

from conftest import gate_ack, session_of, slot_changed, slot_of, snapshot, vehicle


def _session_for(app, outcome_slot):
    return session_of(app, slot_of(app, outcome_slot)["reserved_session_id"])


def test_entry_reserves_first_slot_and_opens_entry_gate(app):
    """SIM-01: một phiên, giữ F1-A1, mở đúng cần vào, OLED chỉ ô."""
    assert ingest.process(app, snapshot(app)) == "SNAPSHOT:18"
    assert ingest.process(app, vehicle(app)) == "RESERVED:F1-A1"

    session = _session_for(app, "F1-A1")
    assert session["state"] == "RESERVED" and session["plate_normalized"] == "51A-12345"
    [gate] = app.publisher.of_type("gate_command")
    assert (gate["gate"], gate["action"], gate["session_id"]) == ("ENTRY", "OPEN", session["session_id"])
    [display] = app.publisher.of_type("display_command")
    assert display["screen"] == "ENTRY_ROUTE" and display["lines"][0] == "VAO: F1-A1"
    assert "51A" not in str(display)  # không gửi biển số lên OLED


def test_replayed_event_has_no_second_effect(app):
    """SIM-10: cùng event_id gửi hai lần."""
    ingest.process(app, snapshot(app))
    event = vehicle(app)
    ingest.process(app, event)
    assert ingest.process(app, dict(event)) == "DUPLICATE"
    assert len(app.publisher.of_type("gate_command")) == 1


def test_car_in_assigned_slot_parks_session(app):
    """SIM-04: ô được gán báo có xe → PARKED; ACK cần vào đến trước thì qua ENTRY_GATE_OPEN."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    command_id = app.publisher.of_type("gate_command")[0]["command_id"]
    assert ingest.process(app, gate_ack(app, command_id)) == "ENTRY:OPEN → ENTRY_GATE_OPEN"
    assert ingest.process(app, slot_changed(app, "F1-A1", True)) == "PARKED:F1-A1"
    assert _session_for(app, "F1-A1")["state"] == "PARKED"


def test_second_car_gets_next_slot_and_same_plate_goes_to_review(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    assert ingest.process(app, vehicle(app, plate="30F-67890")) == "RESERVED:F1-A2"
    assert ingest.process(app, vehicle(app)) == "MANUAL_REVIEW:PLATE_ALREADY_ACTIVE"


def test_contended_slot_moves_to_next(app, monkeypatch):
    """SIM-09: ô trông còn trống lúc đọc nhưng đã bị giữ trước khi ghi → thử ô kế tiếp."""
    ingest.process(app, snapshot(app))
    real_batch_get = app.db.batch_get

    def stale_read(table, keys):
        items = real_batch_get(table, keys)
        if table == app.cfg.tables.slots:
            for item in items:
                item.pop("reserved_session_id", None)
        return items

    ingest.process(app, vehicle(app, plate="30F-67890"))
    monkeypatch.setattr(app.db, "batch_get", stale_read)
    assert ingest.process(app, vehicle(app)) == "RESERVED:F1-A2"


def test_same_plate_racing_is_caught_by_transaction(app, monkeypatch):
    """Hai sự kiện cùng biển số chạy song song: lần kiểm trước bỏ sót, transaction vẫn chặn."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    real_get = app.db.get
    misses = iter([True])

    def get_missing_plate_once(table, key, consistent=True):
        if table == app.cfg.tables.active_plates and next(misses, False):
            return None
        return real_get(table, key, consistent)

    monkeypatch.setattr(app.db, "get", get_missing_plate_once)
    assert ingest.process(app, vehicle(app)) == "MANUAL_REVIEW:PLATE_ALREADY_ACTIVE"
    assert slot_of(app, "F1-A2").get("reserved_session_id") is None


def test_full_lot_does_not_open_gate(app):
    """SIM-06: 18 ô có xe."""
    ingest.process(app, snapshot(app, occupied=SLOT_IDS))
    assert ingest.process(app, vehicle(app)) == "LOT_FULL"
    assert not app.publisher.of_type("gate_command")
    assert app.publisher.of_type("display_command")[0]["screen"] == "LOT_FULL"


def test_stale_slot_board_blocks_assignment(app):
    """SIM-11: quá 90 giây không có snapshot → không gán trên dữ liệu cũ."""
    ingest.process(app, snapshot(app))
    app.clock.advance(seconds=91)
    assert ingest.process(app, vehicle(app)) == "MANUAL_REVIEW:SLOTS_UNKNOWN"
    assert not app.publisher.of_type("gate_command")


def test_uncertain_detections_go_to_manual_review(app):
    """SIM-08 và sự kiện đến trễ: không mở cần tự động."""
    ingest.process(app, snapshot(app))
    assert ingest.process(app, vehicle(app, confidence=0.42)) == "MANUAL_REVIEW:LOW_CONFIDENCE"
    assert ingest.process(app, vehicle(app, color="RED")) == "MANUAL_REVIEW:WRONG_LANE"
    assert ingest.process(app, vehicle(app, plate=None, confidence=0.0)) == "MANUAL_REVIEW:UNREADABLE_PLATE"
    late = vehicle(app, occurred_at=iso(app.clock().replace(minute=0, hour=1)))
    assert ingest.process(app, late) == "MANUAL_REVIEW:STALE_EVENT"
    assert not app.publisher.of_type("gate_command")
    assert {p["screen"] for p in app.publisher.of_type("display_command")} == {"ERROR"}


def test_exit_locks_fee_when_requested(app):
    """UC-06: 61 phút → 15.000 ₫, chờ thu tiền; replay không đổi số tiền."""
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    ingest.process(app, slot_changed(app, "F1-A1", True))
    app.clock.advance(minutes=61)
    ingest.process(app, snapshot(app, occupied={"F1-A1"}))
    exit_event = vehicle(app, lane="EXIT", color="RED")
    assert ingest.process(app, exit_event) == "PAYMENT_PENDING:15000"
    session = _session_for(app, "F1-A1")
    assert (session["fee_vnd"], session["payment_status"]) == (15000, "PENDING")
    assert app.publisher.of_type("display_command")[-1]["screen"] == "EXIT_FEE"

    app.clock.advance(minutes=30)
    assert ingest.process(app, dict(exit_event, occurred_at=iso(app.clock()))) == "DUPLICATE"
    assert _session_for(app, "F1-A1")["fee_vnd"] == 15000


def test_exit_without_parked_session_needs_review(app):
    ingest.process(app, snapshot(app))
    assert ingest.process(app, vehicle(app, lane="EXIT", color="RED")) == "MANUAL_REVIEW:NO_ACTIVE_SESSION"
    ingest.process(app, vehicle(app))
    assert ingest.process(app, vehicle(app, lane="EXIT", color="RED")) == "MANUAL_REVIEW:SESSION_NOT_PARKED"


def test_older_slot_message_is_ignored(app):
    ingest.process(app, snapshot(app))
    newer = slot_changed(app, "F1-A2", True)
    older = slot_changed(app, "F1-A2", False, seq=newer["seq"] - 1)
    ingest.process(app, newer)
    assert ingest.process(app, older) == "STALE:F1-A2"
    assert slot_of(app, "F1-A2")["occupied"] is True


def test_messages_breaking_contract_are_rejected(app):
    spoofed = dict(vehicle(app), device_id="gate-01")
    assert ingest.process(app, spoofed).startswith("INVALID")
    wrong_topic = dict(slot_changed(app, "F1-A2", True), mqtt_topic="parking/v1/site-01/vision/pi-01/events")
    assert ingest.process(app, wrong_topic).startswith("INVALID")
    bad_source = dict(slot_changed(app, "F1-A2", True), source="SENSOR")
    assert ingest.process(app, bad_source).startswith("INVALID")
    partial = snapshot(app)
    partial["slots"] = partial["slots"][:17]
    assert ingest.process(app, partial).startswith("INVALID")
    assert ingest.process(app, dict(vehicle(app), occurred_at="hôm nay")).startswith("INVALID")
    assert ingest.process(app, dict(vehicle(app), schema_version=True)).startswith("INVALID")


def test_gate_error_is_recorded_for_admin(app):
    ingest.process(app, snapshot(app))
    ingest.process(app, vehicle(app))
    command_id = app.publisher.of_type("gate_command")[0]["command_id"]
    ingest.process(app, gate_ack(app, command_id, state="ERROR", error_code="MOTOR_TIMEOUT"))
    assert _session_for(app, "F1-A1")["gate_error"] == "MOTOR_TIMEOUT"
    gate = app.db.get(app.cfg.tables.devices, {"device_id": "gate-01"})
    assert (gate["entry_gate_state"], gate["entry_gate_error"]) == ("ERROR", "MOTOR_TIMEOUT")
