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
CLAIM_TTL = timedelta(minutes=15)
DEVICE_TIMEOUT = timedelta(seconds=90)
IDENTITY_TTL = timedelta(days=10)
PURGE_AFTER = timedelta(days=9, hours=23)
COMMAND_TTL = timedelta(seconds=5)
ACK_TIMEOUT = timedelta(seconds=15)

# 18 ô theo docs/parking-layout.md, đúng thứ tự ưu tiên gán (gần cổng trước).
SLOT_IDS = [f"F{f}-{r}{c}" for f in (1, 2) for r in "ABC" for c in (1, 2, 3)]

OPEN_STATES = ("ENTRY_PENDING", "MANUAL_REVIEW", "RESERVED", "PARKED", "EXIT_REQUESTED", "EXIT_OPENED")
# Xe đang ở trong bãi (đã được cho vào, chưa được cho ra). RESERVED/EXIT_OPENED là trạng thái cũ, giữ để tương thích.
IN_LOT_STATES = ("RESERVED", "PARKED", "EXIT_REQUESTED", "EXIT_OPENED")


def demo_plate(k):
    """Biển số demo của xe thứ k: 11111 … 99999, từ 10 trở đi lặp 3 lần (101010) để không trùng."""
    return str(k) * 5 if k < 10 else str(k) * 3


def demo_number(plate):
    """Ngược của demo_plate; None nếu không phải biển demo."""
    key = plate_key(plate) or ""
    for k in range(1, 100):
        if demo_plate(k) == key:
            return k
    return None


def slot_source(slot_id):  # noqa: ARG001 — giữ chữ ký; sa bàn không còn cảm biến thật
    """Cả 18 ô đều là nút bấm trên sa bàn."""
    return "BUTTON"


def route_steps(slot_id):
    """Lộ trình đầy đủ tiếng Việt cho web/email (khớp hình vẽ RouteMap trên web)."""
    floor, row, col = slot_id[1], slot_id[3], slot_id[4]
    if floor == "1":
        return ["Qua cổng vào, đi theo lối chính bên trái", f"Rẽ phải vào lối đi hàng {row}",
                f"Ô {slot_id} ở cột {col}, phía trên lối đi"]
    return ["Qua cổng vào, đi theo lối chính bên trái đến cuối lối C", "Đi hết lối C, LÊN RAM lên tầng 2",
            f"Tầng 2: đi theo lối chính, rẽ phải vào lối đi hàng {row}", f"Ô {slot_id} ở cột {col}, phía trên lối đi"]


def oled_hint(slot_id, free_count):
    """OLED lúc xe vào (≤ 20 ký tự/dòng): gợi ý ô trống gần nhất, không phải ô được gán."""
    if slot_id is None:
        return ["MOI VAO", "Tu tim cho trong", ""]
    floor, row, col = slot_id[1], slot_id[3], slot_id[4]
    where = f"Tang {floor} hang {row} o {col}"
    return [f"VAO: goi y {slot_id}", where, f"Con {free_count} cho trong"]


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


LOT_TOPIC_LEAF = "lot"  # parking/v1/<site>/vision/pi-01/lot: backend → Pi, danh sách xe trong bãi


def plate_key(text):
    """Khóa so khớp biển số: chỉ chữ/số in hoa ('51a-123.45' → '51A12345')."""
    if not text:
        return None
    key = re.sub(r"[^A-Z0-9]", "", str(text).upper())
    return key or None


def mask_email(email):
    """'nguyenvana@gmail.com' → 'ng***@gmail.com' (đủ để khách nhận ra, không lộ hết)."""
    if not email or "@" not in email:
        return None
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}"


def mask_plate(text):
    if not text:
        return None
    return text[:-3] + "***" if len(text) > 4 else "***"


# ── DynamoDB ───────────────────────────────────────────────────────────────
TABLE_ENV = {
    "slots": "SLOTS_TABLE",
    "plate_emails": "PLATE_EMAILS_TABLE",
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
