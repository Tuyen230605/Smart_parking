"""Sinh ID: ULID cho phiên (sắp theo thời gian), mã rút gọn cho màn hình, UUID cho lệnh."""
import secrets
import uuid
from datetime import datetime

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# Bỏ 0/1 dễ nhầm với O/I khi khách đọc mã trên màn hình.
REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(now: datetime) -> str:
    value = (int(now.timestamp() * 1000) << 80) | int.from_bytes(secrets.token_bytes(10), "big")
    return "".join(CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def new_session_ref() -> str:
    return "".join(secrets.choice(REF_ALPHABET) for _ in range(4))


def new_uuid() -> str:
    return str(uuid.uuid4())
