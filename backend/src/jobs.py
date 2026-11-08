"""Job định kỳ (EventBridge): giám sát mỗi phút, purge mỗi giờ, seed khi deploy.

Input: {"job": "monitor" | "purge" | "seed"}
"""
import core
import logic
import services


def handler(event, _context):
    job = (event or {}).get("job", "monitor")
    if job == "seed":
        return seed()
    if job == "purge":
        return purge()
    return monitor()


def seed():
    """Tạo 18 ô (UNKNOWN cho tới snapshot đầu tiên) và bảng giá mặc định. Chạy lại an toàn."""
    created = 0
    for slot_id in core.SLOT_IDS:
        try:
            core.table("slots").put_item(
                Item={"slot_id": slot_id, "floor": int(slot_id[1]), "row": slot_id[3], "column": int(slot_id[4]),
                      "source": core.slot_source(slot_id), "status": "UNKNOWN", "occupied": False,
                      "updated_at": core.iso(core.now())},
                ConditionExpression="attribute_not_exists(slot_id)",
            )
            created += 1
        except Exception as err:  # noqa: BLE001
            if not core.is_conditional_failure(err):
                raise
    try:
        core.table("pricing").put_item(Item=services.DEFAULT_PRICING,
                                       ConditionExpression="attribute_not_exists(config_id)")
    except Exception as err:  # noqa: BLE001
        if not core.is_conditional_failure(err):
            raise
    return {"slots_created": created}


def monitor():
    at = core.now()
    result = {"offline": [], "expired": [], "ack_timeouts": 0}

    # 1. Thiết bị im lặng > 90 giây → OFFLINE.
    devices = {d["device_id"]: d for d in core.scan_all("devices")}
    for device_id in core.DEVICES:
        d = devices.get(device_id)
        seen = core.parse_iso(d.get("last_seen_at")) if d else None
        stale = not seen or at - seen > core.DEVICE_TIMEOUT
        if stale and d and d.get("state") != "OFFLINE":
            core.table("devices").update_item(
                Key={"device_id": device_id}, UpdateExpression="SET #s = :off",
                ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":off": "OFFLINE"},
            )
            core.alert("DEVICE_OFFLINE", f"{device_id} không gửi dữ liệu quá 90 giây")
        if stale:
            result["offline"].append(device_id)

    # 2. Board ô offline → mọi ô UNKNOWN, không gán dựa trên dữ liệu cũ (SIM-11).
    if core.SLOTS_ID in result["offline"]:
        for slot in core.scan_all("slots"):
            if slot.get("status") not in ("UNKNOWN", "OUT_OF_SERVICE"):
                core.table("slots").update_item(
                    Key={"slot_id": slot["slot_id"]}, UpdateExpression="SET #s = :u, updated_at = :now",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":u": "UNKNOWN", ":now": core.iso(at)},
                )

    # 3. Lệnh cần chắn không ACK đúng hạn.
    gate = devices.get(core.GATE_ID) or {}
    for cmd_id, info in (gate.get("pending_commands") or {}).items():
        if at - core.parse_iso(info["issued_at"]) > core.ACK_TIMEOUT:
            core.table("devices").update_item(
                Key={"device_id": core.GATE_ID}, UpdateExpression="REMOVE pending_commands.#c",
                ExpressionAttributeNames={"#c": cmd_id},
            )
            core.alert("GATE_NO_ACK", f"Cần {info['gate']} không phản hồi lệnh {info['action']}", level="ERROR")
            result["ack_timeouts"] += 1

    # 4. Giữ ô quá 5 phút mà xe chưa vào → EXPIRED, giải phóng ô nếu vẫn trống (SIM-13).
    reserved = core.scan_all("sessions", FilterExpression="#s = :r",
                             ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":r": "RESERVED"})
    for s in reserved:
        if at - core.parse_iso(s["reserved_at"]) <= core.RESERVATION_TIMEOUT:
            continue
        try:
            core.table("sessions").update_item(
                Key={"session_id": s["session_id"]}, ConditionExpression="#s = :r",
                UpdateExpression="SET #s = :e, expired_at = :now, history = list_append(history, :h) REMOVE claim_nonce",
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={":r": "RESERVED", ":e": "EXPIRED", ":now": core.iso(at),
                                           ":h": [{"at": core.iso(at), "actor": "system", "action": "EXPIRED"}]},
            )
        except Exception as err:  # noqa: BLE001
            if core.is_conditional_failure(err):
                continue
            raise
        _release_slot(s["slot_id"], s["session_id"])
        logic.release_plate(s)
        core.alert("RESERVATION_EXPIRED", f"Lượt {s['session_ref']} không vào ô {s['slot_id']} sau 5 phút",
                   session_id=s["session_id"])
        result["expired"].append(s["session_id"])
    return result


def _release_slot(slot_id, session_id):
    names = {"#s": "status"}
    try:  # còn RESERVED cho đúng phiên → trống lại
        core.table("slots").update_item(
            Key={"slot_id": slot_id}, ConditionExpression="#s = :r AND reserved_session_id = :sid",
            UpdateExpression="SET #s = :a, updated_at = :now REMOVE reserved_session_id",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues={":r": "RESERVED", ":a": "AVAILABLE", ":sid": session_id,
                                       ":now": core.iso(core.now())},
        )
        return
    except Exception as err:  # noqa: BLE001
        if not core.is_conditional_failure(err):
            raise
    try:  # UNKNOWN/OCCUPIED: chỉ gỡ liên kết phiên, giữ trạng thái hiện trường
        core.table("slots").update_item(
            Key={"slot_id": slot_id}, ConditionExpression="reserved_session_id = :sid",
            UpdateExpression="REMOVE reserved_session_id", ExpressionAttributeValues={":sid": session_id},
        )
    except Exception as err:  # noqa: BLE001
        if not core.is_conditional_failure(err):
            raise


def purge():
    """Xóa biển số/email/token đã thu thập quá 9 ngày 23 giờ (UC-10)."""
    at = core.now()
    cutoff = core.iso(at - core.PURGE_AFTER)
    purged = 0
    sessions = core.scan_all(
        "sessions",
        FilterExpression="(attribute_exists(plate_normalized) AND plate_collected_at < :c) OR "
                         "(attribute_exists(email) AND email_collected_at < :c) OR "
                         "(attribute_exists(claim_nonce) AND created_at < :c)",
        ExpressionAttributeValues={":c": cutoff},
    )
    for s in sessions:
        if s.get("state") in core.OPEN_STATES:
            core.alert("PURGE_OPEN_SESSION", f"Lượt {s['session_ref']} còn mở sát hạn 10 ngày, đã xóa định danh",
                       session_id=s["session_id"])
        logic.release_plate(s)
        core.table("sessions").update_item(
            Key={"session_id": s["session_id"]},
            UpdateExpression="SET identity_purged_at = :now REMOVE plate_normalized, plate_display, email, claim_nonce",
            ExpressionAttributeValues={":now": core.iso(at)},
        )
        purged += 1
    return {"purged": purged}
