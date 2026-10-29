from datetime import datetime, timedelta, timezone

import pytest

from parking.claims import InvalidToken, KeyRing, new_nonce, parse_keys, sign_claim, verify_claim
from parking.ids import new_ulid
from parking.layout import SLOT_IDS, oled_route_lines, route_steps
from parking.plates import normalize_plate
from parking.pricing import DEFAULT_PRICING, compute_fee
from parking.timeutil import parse_iso

T0 = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)
KEY_A = "a" * 32
KEY_B = "b" * 32


@pytest.mark.parametrize("minutes, fee", [
    (0, 0), (14.99, 0), (15, 10_000), (60, 10_000), (61, 15_000), (120, 15_000), (121, 20_000),
])
def test_fee_table_from_contract(minutes, fee):
    assert compute_fee(DEFAULT_PRICING, T0, T0 + timedelta(minutes=minutes)) == fee


def test_slots_order_and_routes():
    assert SLOT_IDS[0] == "F1-A1" and SLOT_IDS[-1] == "F2-C3" and len(SLOT_IDS) == 18
    assert route_steps("F2-C3") == ["Lên ram tầng 2", "Đi đến hàng C", "Ô số 3"]
    for slot_id in SLOT_IDS:
        lines = oled_route_lines(slot_id)
        assert len(lines) == 3 and all(len(line) <= 20 and line.isascii() for line in lines)


@pytest.mark.parametrize("raw, plate", [
    ("51A-12345", "51A-12345"), ("51a 123.45", "51A-12345"), ("59X1-23456", "59X1-23456"),
    ("51A12345", "51A-12345"), ("51A-1Z345", None), ("", None), (None, None), ("xx 51A-12345", None),
])
def test_normalize_plate(raw, plate):
    assert normalize_plate(raw) == plate


def test_claim_token_roundtrip_and_tamper():
    keys = parse_keys(KEY_A)
    sid, nonce = new_ulid(T0), new_nonce()
    token = sign_claim(keys, sid, nonce, 1_800_000_000)
    ref = verify_claim(keys, token)
    assert (ref.session_id, ref.nonce, ref.expires_epoch) == (sid, nonce, 1_800_000_000)
    with pytest.raises(InvalidToken):
        verify_claim(keys, token.replace("1800000000", "1900000000"))
    with pytest.raises(InvalidToken):
        verify_claim(parse_keys(KEY_B), token)


def test_key_rotation_accepts_previous_key():
    old_token = sign_claim(parse_keys(KEY_A), new_ulid(T0), new_nonce(), 1_800_000_000)
    verify_claim(parse_keys(f"{KEY_B},{KEY_A}"), old_token)
    with pytest.raises(ValueError):
        parse_keys("short")


def test_keyring_reloads_after_ttl():
    values, now = iter([KEY_A, KEY_B]), [0.0]
    ring = KeyRing(lambda: next(values), ttl_s=300, clock=lambda: now[0])
    assert ring.keys() == [KEY_A.encode()]
    now[0] = 301
    assert ring.keys() == [KEY_B.encode()]


@pytest.mark.parametrize("value", ["2026-10-29T02:00:00", "29/10/2026", "2026-10-29T02:00:00Zjunk", 1730000000])
def test_timestamps_need_timezone(value):
    with pytest.raises(ValueError):
        parse_iso(value)
