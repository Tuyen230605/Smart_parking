"""DynamoDB giả bằng moto, publisher/mailer giả và đồng hồ điều khiển được."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from parking.app import App
from parking.claims import KeyRing
from parking.config import Config
from parking.layout import SLOT_IDS, source_of
from parking.store import Db
from parking.timeutil import iso
from schema import LOCAL_TABLES as TABLES, create_tables

KEY = "test-key-0123456789abcdefghijklmnopqrstuvwxyz"
SITE = "site-01"
BOOT = "91270fd2-a4ad-4ccf-a11d-af3657c4e32e"


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakePublisher:
    def __init__(self):
        self.messages: list[tuple[str, dict]] = []

    def publish(self, topic, payload):
        self.messages.append((topic, payload))

    def of_type(self, message_type):
        return [p for _, p in self.messages if p["message_type"] == message_type]


class FakeMailer:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    def send(self, to, subject, text):
        if self.fail:
            raise RuntimeError("SES từ chối")
        self.sent.append((to, subject, text))
        return f"msg-{len(self.sent)}"


@pytest.fixture
def app(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                        "AWS_DEFAULT_REGION": "ap-southeast-2"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        client = boto3.client("dynamodb")
        create_tables(client)
        cfg = Config(site_id=SITE, tables=TABLES, web_base_url="https://web.test", ses_sender="noreply@web.test",
                     claim_keys=KEY)
        yield App(cfg, Db(client), FakePublisher(), FakeMailer(), KeyRing(lambda: KEY),
                  Clock(datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)))


_seq = itertools.count(1)


def message(app, message_type, kind, device, leaf, **fields):
    return {
        "mqtt_topic": f"parking/v1/{SITE}/{kind}/{device}/{leaf}",
        "schema_version": 1,
        "message_type": message_type,
        "event_id": str(uuid.uuid4()),
        "device_id": device,
        "boot_id": BOOT,
        "seq": next(_seq),
        "occurred_at": iso(app.clock()),
        **fields,
    }


def vehicle(app, lane="ENTRY", color="GREEN", plate="51A-12345", confidence=0.93, **fields):
    return message(app, "vehicle_detected", "vision", "pi-01", "events", lane_id=lane, card_color=color,
                   plate_text=plate, plate_confidence=confidence, **fields)


def snapshot(app, occupied=()):
    slots = [{"slot_id": sid, "occupied": sid in occupied, "source": source_of(sid)} for sid in SLOT_IDS]
    return message(app, "slots_snapshot", "slots", "slots-01", "state", slots=slots)


def slot_changed(app, slot_id, occupied, **fields):
    return message(app, "slot_changed", "slots", "slots-01", "state", slot_id=slot_id, occupied=occupied,
                   source=source_of(slot_id), **fields)


def gate_ack(app, command_id, gate="ENTRY", state="OPEN", error_code=None):
    return message(app, "gate_telemetry", "gates", "gate-01", "telemetry", command_id=command_id, gate=gate,
                   state=state, error_code=error_code)


def device_status(app, device, state="ONLINE"):
    return message(app, "device_status", "devices", device, "status", state=state, firmware_version="0.1.0")


def session_of(app, session_id):
    return app.db.get(app.cfg.tables.sessions, {"session_id": session_id})


def slot_of(app, slot_id):
    return app.db.get(app.cfg.tables.slots, {"slot_id": slot_id})
