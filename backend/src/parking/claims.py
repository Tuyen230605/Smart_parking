"""Token QR phiên: session_id + nonce 128 bit + hạn, ký HMAC-SHA256 (docs/api-contract.md §1).

Token không lưu trong DB; kiosk lấy lại URL bằng cách ký lại từ dữ liệu phiên. Đổi khóa: đặt
"khóa_mới,khóa_cũ" để token cũ còn dùng được đến khi hết hạn, sau ít nhất 20 phút thì bỏ khóa cũ.
"""
import base64
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from typing import Callable

TOKEN_RE = re.compile(
    r"(?P<sid>[0-9A-HJKMNP-TV-Z]{26})\.(?P<nonce>[A-Za-z0-9_-]{22})\.(?P<exp>\d{10})\.(?P<sig>[A-Za-z0-9_-]{22})"
)
MIN_KEY_LENGTH = 32


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class ClaimRef:
    session_id: str
    nonce: str
    expires_epoch: int


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_nonce() -> str:
    return _b64(secrets.token_bytes(16))


def _mac(key: bytes, payload: str) -> str:
    return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest()[:16])


def sign_claim(keys: list[bytes], session_id: str, nonce: str, expires_epoch: int) -> str:
    payload = f"{session_id}.{nonce}.{expires_epoch}"
    return f"{payload}.{_mac(keys[0], payload)}"


def verify_claim(keys: list[bytes], token: str) -> ClaimRef:
    """Chỉ kiểm định dạng và chữ ký; hạn và nonce hiện hành do caller so với phiên."""
    m = TOKEN_RE.fullmatch(token or "")
    if not m:
        raise InvalidToken("sai định dạng")
    payload = f"{m['sid']}.{m['nonce']}.{m['exp']}"
    if not any(hmac.compare_digest(_mac(key, payload), m["sig"]) for key in keys):
        raise InvalidToken("sai chữ ký")
    return ClaimRef(m["sid"], m["nonce"], int(m["exp"]))


def parse_keys(value: str) -> list[bytes]:
    keys = [k.strip() for k in value.split(",") if k.strip()]
    if not keys or any(len(k) < MIN_KEY_LENGTH for k in keys):
        raise ValueError(f"cần ít nhất một khóa HMAC dài ≥ {MIN_KEY_LENGTH} ký tự")
    return [k.encode() for k in keys]


class KeyRing:
    """Cache khóa 5 phút để không gọi SSM mỗi request nhưng vẫn nhận khóa mới sau khi đổi."""

    def __init__(self, load: Callable[[], str], ttl_s: float = 300, clock: Callable[[], float] = time.monotonic):
        self._load, self._ttl_s, self._clock = load, ttl_s, clock
        self._keys: list[bytes] | None = None
        self._loaded_at = 0.0

    def keys(self) -> list[bytes]:
        if self._keys is None or self._clock() - self._loaded_at > self._ttl_s:
            self._keys = parse_keys(self._load())
            self._loaded_at = self._clock()
        return self._keys
