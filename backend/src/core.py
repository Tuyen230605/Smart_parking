"""Hạ tầng dùng chung cho mọi Lambda: cấu hình, bảng DynamoDB, thời gian, ID, layout bãi.

Không log biển số/email/token. Chỉ log loại message và ID.
"""
import json
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache

import boto3

log = logging.getLogger("parking")
log.setLevel(logging.INFO)

SITE_ID = os.environ.get("SITE_ID", "site-01")
PI_ID, GATE_ID, SLOTS_ID = "pi-01", "gate-01", "slots-01"
DEVICES = (PI_ID, GATE_ID, SLOTS_ID)

PLATE_THRESHOLD = float(os.environ.get("PLATE_THRESHOLD", "0.85"))
RESERVATION_TIMEOUT = timedelta(minutes=5)
CLAIM_TTL = timedelta(minutes=15)
DEVICE_TIMEOUT = timedelta(seconds=90)
IDENTITY_TTL = timedelta(days=10)
PURGE_AFTER = timedelta(days=9, hours=23)
COMMAND_TTL = timedelta(seconds=5)
ACK_TIMEOUT = timedelta(seconds=15)

# 18 ô theo docs/parking-layout.md, đúng thứ tự ưu tiên gán (gần cổng trước).
SLOT_IDS = [f"F{f}-{r}{c}" for f in (1, 2) for r in "ABC" for c in (1, 2, 3)]
SENSOR_SLOT = "F1-A1"

OPEN_STATES = ("MANUAL_REVIEW", "RESERVED", "PARKED", "EXIT_REQUESTED", "EXIT_OPENED")


def slot_source(slot_id):
    return "SENSOR" if slot_id == SENSOR_SLOT else "BUTTON"


def route_steps(slot_id):
    """Lộ trình đầy đủ tiếng Việt cho web/email."""
    floor, row, col = slot_id[1], slot_id[3], slot_id[4]
    first = "Tầng 1, đi thẳng từ cổng vào" if floor == "1" else f"Lên ram tầng {floor}"
    return [first, f"Đi đến hàng {row}", f"Ô số {col}"]


def oled_route(slot_id):
    """Bản rút gọn ASCII ≤ 20 ký tự/dòng cho OLED."""
    floor, row, col = slot_id[1], slot_id[3], slot_id[4]
    second = f"Tang 1 - Hang {row}" if floor == "1" else f"Len tang {floor}-Hang {row}"
    return [f"VAO: {slot_id}", second, f"O so {col}"]


# ── thời gian ──────────────────────────────────────────────────────────────
def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def epoch(dt):
    return int(dt.timestamp())


# ── ID ─────────────────────────────────────────────────────────────────────
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid():
    """ULID 26 ký tự: sắp xếp được theo thời gian tạo."""
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


def short_ref():
    return "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4))


def new_uuid():
    return str(uuid.uuid4())


def plate_key(text):
    """Khóa so khớp biển số: chỉ chữ/số in hoa ('51a-123.45' → '51A12345')."""
    if not text:
        return None
    key = re.sub(r"[^A-Z0-9]", "", str(text).upper())
    return key or None


def mask_plate(text):
    if not text:
        return None
    return text[:-3] + "***" if len(text) > 4 else "***"


# ── DynamoDB ───────────────────────────────────────────────────────────────
TABLE_ENV = {
    "slots": "SLOTS_TABLE",
    "sessions": "SESSIONS_TABLE",
    "plates": "ACTIVE_PLATES_TABLE",
    "processed": "PROCESSED_TABLE",
    "devices": "DEVICES_TABLE",
    "pricing": "PRICING_TABLE",
    "alerts": "ALERTS_TABLE",
}


@lru_cache(maxsize=None)
def ddb():
    return boto3.resource("dynamodb")


@lru_cache(maxsize=None)
def table(name):
    return ddb().Table(table_name(name))


def table_name(name):
    return os.environ.get(TABLE_ENV[name], f"smart-parking-{name}")


def client():
    """Client của resource: nhận kiểu Python thường cho transact_write_items."""
    return ddb().meta.client


def scan_all(name, **kwargs):
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = table(name).scan(**kwargs)
        items.extend(page.get("Items", []))
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def is_conditional_failure(err):
    return getattr(err, "response", {}).get("Error", {}).get("Code") in (
        "ConditionalCheckFailedException",
        "TransactionCanceledException",
    )


def plain(value):
    """Decimal của DynamoDB → int/float để json.dumps được."""
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def dumps(obj):
    return json.dumps(plain(obj), ensure_ascii=False)


# ── cảnh báo cho quản trị ──────────────────────────────────────────────────
def alert(kind, message, level="WARN", session_id=None):
    """Ghi một cảnh báo cho dashboard. Không đưa biển số/email vào `message`."""
    at = now()
    item = {
        "alert_id": ulid(),
        "kind": kind,
        "level": level,
        "message": message,
        "created_at": iso(at),
        "acked": False,
        "ttl": epoch(at + IDENTITY_TTL),
    }
    if session_id:
        item["session_id"] = session_id
    table("alerts").put_item(Item=item)
    log.info("alert %s %s", kind, item["alert_id"])
    return item


# ── chống xử lý trùng ──────────────────────────────────────────────────────
def processed_item(message_id, kind):
    at = now()
    return {"message_id": message_id, "kind": kind, "processed_at": iso(at), "ttl": epoch(at + IDENTITY_TTL)}


def already_processed(message_id):
    return "Item" in table("processed").get_item(Key={"message_id": message_id}, ProjectionExpression="message_id")


def mark_processed(message_id, kind):
    """True nếu đây là lần đầu; False nếu message đã được xử lý."""
    try:
        table("processed").put_item(
            Item=processed_item(message_id, kind),
            ConditionExpression="attribute_not_exists(message_id)",
        )
        return True
    except Exception as err:  # noqa: BLE001 — chỉ nuốt lỗi điều kiện
        if is_conditional_failure(err):
            return False
        raise
