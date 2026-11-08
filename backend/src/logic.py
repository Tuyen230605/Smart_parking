"""Nghiệp vụ bãi xe: gán ô nguyên tử, vào/ra, tính phí, cảm biến ô, duyệt thủ công.

Trạng thái phiên:
  MANUAL_REVIEW → (admin) RESERVED | RESOLVED | REJECTED
  RESERVED → PARKED → EXIT_REQUESTED → EXIT_OPENED → CLOSED
  RESERVED → EXPIRED (5 phút không vào ô)
"""
import secrets

import core
import services


class BusinessError(Exception):
    """Lỗi nghiệp vụ có HTTP status và mã theo docs/api-contract.md."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _history(actor, action, reason=None):
    entry = {"at": core.iso(core.now()), "actor": actor, "action": action}
    if reason:
        entry["reason"] = reason
    return entry


def get_session(session_id):
    item = core.table("sessions").get_item(Key={"session_id": session_id}).get("Item")
    if not item:
        raise BusinessError(404, "NOT_FOUND", "Không tìm thấy phiên")
    return item


def _identity_fields(plate_text, confidence, at):
    if not plate_text:
        return {}
    return {
        "plate_normalized": core.plate_key(plate_text),
        "plate_display": plate_text,
        "plate_confidence": services.to_decimal(round(float(confidence or 0), 3)),
        "plate_collected_at": core.iso(at),
        "identity_expires_at": core.iso(at + core.IDENTITY_TTL),
    }


# ── sự kiện từ Pi ──────────────────────────────────────────────────────────


def handle_vehicle_detected(msg):
    event_id = msg["event_id"]
    if core.already_processed(event_id):
        return {"result": "DUPLICATE"}
    lane, color = msg.get("lane_id"), msg.get("card_color")
    plate, conf = msg.get("plate_text"), float(msg.get("plate_confidence") or 0)

    problems = []
    if (lane, color) not in (("ENTRY", "GREEN"), ("EXIT", "RED")):
        problems.append(f"WRONG_LANE:{lane}+{color}")
    if not core.plate_key(plate):
        problems.append("NO_PLATE")
    elif conf < core.PLATE_THRESHOLD:
        problems.append("LOW_CONFIDENCE")
    if problems:
        return create_review(lane, plate, conf, ",".join(problems), event_id)
    if lane == "ENTRY":
        return entry(plate, conf, event_id=event_id, actor=core.PI_ID)
    return request_exit(plate, conf, event_id=event_id, actor=core.PI_ID)


def create_review(lane, plate, conf, reason, event_id=None):
    if event_id and not core.mark_processed(event_id, "vehicle_detected"):
        return {"result": "DUPLICATE"}
    at = core.now()
    session = {
        "session_id": core.ulid(),
        "session_ref": core.short_ref(),
        "state": "MANUAL_REVIEW",
        "review_lane": lane if lane in ("ENTRY", "EXIT") else "ENTRY",
        "review_reason": reason,
        "created_at": core.iso(at),
        "history": [_history(core.PI_ID, "MANUAL_REVIEW", reason)],
        **_identity_fields(plate, conf, at),
    }
    core.table("sessions").put_item(Item=session)
    core.alert("MANUAL_REVIEW", f"Lượt {session['session_ref']} ở làn {session['review_lane']} cần duyệt: {reason}",
               session_id=session["session_id"])
    services.display_command("ERROR", ["CHO NHAN VIEN", "Dang kiem tra xe", f"Ma {session['session_ref']}"])
    return {"result": "MANUAL_REVIEW", "session_id": session["session_id"]}


# ── vào bãi ────────────────────────────────────────────────────────────────


def assignable_slots():
    """Ô AVAILABLE theo thứ tự ưu tiên; rỗng nếu board ô offline (UC-04: không gán trên dữ liệu cũ)."""
    if not services.device_online(core.SLOTS_ID):
        return []
    slots = {s["slot_id"]: s for s in core.scan_all("slots")}
    return [
        sid for sid in core.SLOT_IDS
        if sid in slots and slots[sid].get("status") == "AVAILABLE" and not slots[sid].get("reserved_session_id")
    ]


def entry(plate, conf, event_id=None, actor="system", review_session=None, reason=None):
    """Giữ một ô + tạo phiên + khóa biển số trong cùng một transaction rồi mở cần vào."""
    key = core.plate_key(plate)
    at = core.now()
    nonce = secrets.token_urlsafe(16)  # 128 bit
    base = {
        "state": "RESERVED",
        "checkin_at": core.iso(at),
        "reserved_at": core.iso(at),
        "claim_nonce": nonce,
        "claim_expires_at": core.iso(at + core.CLAIM_TTL),
        "pricing": services.current_pricing(),
        **_identity_fields(plate, conf, at),
    }
    if review_session:
        session_id, session_ref = review_session["session_id"], review_session["session_ref"]
    else:
        session_id, session_ref = core.ulid(), core.short_ref()

    candidates = assignable_slots()
    for slot_id in candidates:
        items = [{
            "Update": {
                "TableName": core.table_name("slots"),
                "Key": {"slot_id": slot_id},
                "ConditionExpression": "#st = :avail AND attribute_not_exists(reserved_session_id)",
                "UpdateExpression": "SET #st = :res, reserved_session_id = :sid, updated_at = :now",
                "ExpressionAttributeNames": {"#st": "status"},
                "ExpressionAttributeValues": {":avail": "AVAILABLE", ":res": "RESERVED", ":sid": session_id,
                                              ":now": core.iso(at)},
            }
        }]
        if review_session:
            fields = {**base, "slot_id": slot_id, "resolved_by": actor}
            names = {f"#{k}": k for k in fields}
            values = {f":{k}": v for k, v in fields.items()}
            values[":review"] = "MANUAL_REVIEW"
            values[":h"] = [_history(actor, "RESOLVE_ENTRY", reason)]
            items.append({"Update": {
                "TableName": core.table_name("sessions"),
                "Key": {"session_id": session_id},
                "ConditionExpression": "#state = :review",
                "UpdateExpression": "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
                                    + ", history = list_append(history, :h)",
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }})
        else:
            items.append({"Put": {
                "TableName": core.table_name("sessions"),
                "ConditionExpression": "attribute_not_exists(session_id)",
                "Item": {"session_id": session_id, "session_ref": session_ref, "slot_id": slot_id,
                         "created_at": core.iso(at), "history": [_history(actor, "ENTRY")], **base},
            }})
        items.append({"Put": {
            "TableName": core.table_name("plates"),
            "ConditionExpression": "attribute_not_exists(plate_normalized)",
            "Item": {"plate_normalized": key, "session_id": session_id, "created_at": core.iso(at),
                     "ttl": core.epoch(at + core.IDENTITY_TTL)},
        }})
        if event_id:
            items.append({"Put": {
                "TableName": core.table_name("processed"),
                "ConditionExpression": "attribute_not_exists(message_id)",
                "Item": core.processed_item(event_id, "vehicle_detected"),
            }})
        try:
            core.client().transact_write_items(TransactItems=items)
        except core.client().exceptions.TransactionCanceledException as err:
            codes = [r.get("Code") for r in err.response.get("CancellationReasons", [])]
            if len(codes) > 3 and codes[3] == "ConditionalCheckFailed":
                return {"result": "DUPLICATE"}
            if codes[2] == "ConditionalCheckFailed":
                if review_session:
                    raise BusinessError(409, "INVALID_STATE", "Biển số này đang có phiên mở") from err
                return create_review("ENTRY", plate, conf, "PLATE_ALREADY_ACTIVE", event_id)
            if codes[1] == "ConditionalCheckFailed":
                raise BusinessError(409, "INVALID_STATE", "Phiên không còn ở trạng thái chờ duyệt") from err
            continue  # chỉ ô bị giữ trước → thử ô kế tiếp (SIM-09)
        core.log.info("session %s reserved", session_id)
        services.gate_command("ENTRY", "OPEN", session_id)
        services.display_command("ENTRY_ROUTE", core.oled_route(slot_id))
        if not services.device_online(core.GATE_ID):
            core.alert("DEVICE_OFFLINE", f"Đã gán ô {slot_id} cho lượt {session_ref} nhưng ESP cổng đang offline",
                       session_id=session_id)
        return {"result": "RESERVED", "session_id": session_id, "slot_id": slot_id}

    # Không còn ô hợp lệ → bãi đầy, không mở cần.
    if event_id and not core.mark_processed(event_id, "vehicle_detected"):
        return {"result": "DUPLICATE"}
    services.display_command("LOT_FULL", ["BAI DA DAY", "Xin loi quy khach", "Vui long quay lai"])
    core.alert("LOT_FULL", "Xe yêu cầu vào nhưng không còn ô trống/đáng tin", level="INFO")
    if review_session:
        raise BusinessError(409, "SLOT_CONFLICT", "Không còn ô trống để gán")
    return {"result": "LOT_FULL"}


# ── ra bãi ─────────────────────────────────────────────────────────────────


def find_active_session(plate):
    key = core.plate_key(plate)
    if not key:
        return None
    ap = core.table("plates").get_item(Key={"plate_normalized": key}).get("Item")
    if not ap:
        return None
    return core.table("sessions").get_item(Key={"session_id": ap["session_id"]}).get("Item")


def request_exit(plate, conf, event_id=None, actor="system"):
    session = find_active_session(plate)
    if not session or session["state"] not in ("RESERVED", "PARKED", "EXIT_REQUESTED", "EXIT_OPENED"):
        if actor == core.PI_ID:
            return create_review("EXIT", plate, conf, "NO_ACTIVE_SESSION", event_id)
        raise BusinessError(404, "NOT_FOUND", "Không có phiên đang đỗ với biển số này")
    if event_id and not core.mark_processed(event_id, "vehicle_detected"):
        return {"result": "DUPLICATE"}

    if session["state"] in ("EXIT_REQUESTED", "EXIT_OPENED"):
        # Thẻ đỏ quét lại: hiện lại phí đã khóa, không tính lại.
        _show_fee(session)
        return {"result": session["state"], "session_id": session["session_id"]}

    at = core.now()
    fee = services.compute_fee(session.get("pricing") or services.current_pricing(),
                               core.parse_iso(session["checkin_at"]), at)
    payment = "NO_CHARGE" if fee == 0 else "PENDING"
    try:
        session = core.table("sessions").update_item(
            Key={"session_id": session["session_id"]},
            ConditionExpression="#s IN (:r, :p)",
            UpdateExpression="SET #s = :er, exit_requested_at = :at, charge_end_at = :at, fee_vnd = :fee, "
                             "payment_status = :pay, history = list_append(history, :h)",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":r": "RESERVED", ":p": "PARKED", ":er": "EXIT_REQUESTED", ":at": core.iso(at),
                                       ":fee": fee, ":pay": payment, ":h": [_history(actor, "EXIT_REQUEST")]},
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except Exception as err:  # noqa: BLE001
        if core.is_conditional_failure(err):
            return {"result": "INVALID_STATE"}
        raise
    _show_fee(session)
    if payment == "NO_CHARGE":
        try:
            open_exit(session["session_id"], actor="system")
        except BusinessError as err:
            core.alert("DEVICE_OFFLINE", f"Lượt {session['session_ref']} miễn phí nhưng chưa mở được cổng ra: {err.message}",
                       session_id=session["session_id"])
    else:
        core.alert("PAYMENT_PENDING", f"Lượt {session['session_ref']} chờ thu {services.format_vnd(fee)} ₫",
                   level="INFO", session_id=session["session_id"])
    return {"result": "EXIT_REQUESTED", "session_id": session["session_id"], "fee_vnd": fee}


def _show_fee(session):
    fee = int(session.get("fee_vnd") or 0)
    third = "Mien phi - Moi ra" if fee == 0 else ("Da thu - Moi ra" if session.get("payment_status") in
                                                 ("PAID_CASH", "WAIVED") else "Moi thanh toan")
    services.display_command("EXIT_FEE", [f"RA: {session.get('slot_id', '?')}", f"Phi: {fee} VND", third])


def record_payment(session_id, status, amount, note, actor):
    if status not in ("PAID_CASH", "WAIVED"):
        raise BusinessError(400, "INVALID_INPUT", "payment_status phải là PAID_CASH hoặc WAIVED")
    if status == "WAIVED" and not (note or "").strip():
        raise BusinessError(400, "INVALID_INPUT", "Miễn phí (WAIVED) cần ghi lý do")
    session = get_session(session_id)
    if session["state"] != "EXIT_REQUESTED" or session.get("payment_status") != "PENDING":
        raise BusinessError(409, "INVALID_STATE", "Phiên không ở trạng thái chờ thu tiền")
    if status == "PAID_CASH" and amount is not None and int(amount) != int(session["fee_vnd"]):
        raise BusinessError(400, "INVALID_INPUT", f"Số tiền phải bằng phí đã khóa {session['fee_vnd']} ₫")
    try:
        core.table("sessions").update_item(
            Key={"session_id": session_id},
            ConditionExpression="#s = :er AND payment_status = :pending",
            UpdateExpression="SET payment_status = :pay, payment_note = :note, paid_at = :at, paid_by = :actor, "
                             "history = list_append(history, :h)",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":er": "EXIT_REQUESTED", ":pending": "PENDING", ":pay": status,
                                       ":note": note or "", ":at": core.iso(core.now()), ":actor": actor,
                                       ":h": [_history(actor, status, note)]},
        )
    except Exception as err:  # noqa: BLE001
        if core.is_conditional_failure(err):
            raise BusinessError(409, "INVALID_STATE", "Phiên vừa thay đổi, tải lại trang") from err
        raise
    return open_exit(session_id, actor)


def open_exit(session_id, actor):
    session = get_session(session_id)
    if session["state"] not in ("EXIT_REQUESTED", "EXIT_OPENED"):
        raise BusinessError(409, "INVALID_STATE", "Phiên chưa yêu cầu ra")
    if session.get("payment_status") not in ("NO_CHARGE", "PAID_CASH", "WAIVED"):
        raise BusinessError(409, "INVALID_STATE", "Chưa ghi nhận thu tiền")
    if not services.device_online(core.GATE_ID):
        raise BusinessError(503, "DEVICE_OFFLINE", "ESP cổng đang offline, không thể mở cần an toàn")
    cmd = services.gate_command("EXIT", "OPEN", session_id)
    session = core.table("sessions").update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :eo, exit_opened_at = :at, history = list_append(history, :h)",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":eo": "EXIT_OPENED", ":at": core.iso(core.now()),
                                   ":h": [_history(actor, "OPEN_EXIT", cmd["command_id"])]},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    _show_fee(session)
    return session


def confirm_passage(session_id, actor):
    session = get_session(session_id)
    if session["state"] != "EXIT_OPENED":
        raise BusinessError(409, "INVALID_STATE", "Cổng ra chưa được mở cho phiên này")
    at = core.now()
    session = core.table("sessions").update_item(
        Key={"session_id": session_id},
        ConditionExpression="#s = :eo",
        UpdateExpression="SET #s = :closed, exit_confirmed_at = :at, history = list_append(history, :h) "
                         "REMOVE claim_nonce, email",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":eo": "EXIT_OPENED", ":closed": "CLOSED", ":at": core.iso(at),
                                   ":h": [_history(actor, "CONFIRM_PASSAGE")]},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    release_plate(session)
    services.display_command("IDLE", ["SMART PARKING", "Xin chao", ""], seconds=5)
    slot = core.table("slots").get_item(Key={"slot_id": session.get("slot_id", "-")}).get("Item")
    if slot and slot.get("occupied"):
        core.alert("SLOT_MISMATCH", f"Lượt {session['session_ref']} đã ra nhưng ô {slot['slot_id']} vẫn báo có xe",
                   session_id=session_id)
    return session


def release_plate(session):
    key = session.get("plate_normalized")
    if not key:
        return
    try:
        core.table("plates").delete_item(
            Key={"plate_normalized": key},
            ConditionExpression="session_id = :sid",
            ExpressionAttributeValues={":sid": session["session_id"]},
        )
    except Exception as err:  # noqa: BLE001
        if not core.is_conditional_failure(err):
            raise


# ── duyệt thủ công ─────────────────────────────────────────────────────────


def resolve_review(session_id, body, actor):
    session = get_session(session_id)
    if session["state"] != "MANUAL_REVIEW":
        raise BusinessError(409, "INVALID_STATE", "Phiên không chờ duyệt")
    action = (body.get("action") or "").upper()
    reason = (body.get("reason") or "").strip() or "Quản trị xác nhận"
    if action == "REJECT":
        core.table("sessions").update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #s = :rej, history = list_append(history, :h)",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":rej": "REJECTED", ":h": [_history(actor, "REJECT", reason)]},
        )
        return get_session(session_id)
    plate = body.get("plate_text")
    if not core.plate_key(plate):
        raise BusinessError(400, "INVALID_INPUT", "Cần nhập biển số")
    if action == "ENTRY":
        result = entry(plate, 1.0, actor=actor, review_session=session, reason=reason)
        return get_session(result["session_id"])
    if action == "EXIT":
        result = request_exit(plate, 1.0, actor=actor)
        core.table("sessions").update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #s = :done, linked_session_id = :sid, history = list_append(history, :h)",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":done": "RESOLVED", ":sid": result["session_id"],
                                       ":h": [_history(actor, "RESOLVE_EXIT", reason)]},
        )
        return get_session(result["session_id"])
    raise BusinessError(400, "INVALID_INPUT", "action phải là ENTRY, EXIT hoặc REJECT")


def renew_claim(session_id, actor):
    session = get_session(session_id)
    if session["state"] not in ("RESERVED", "PARKED"):
        raise BusinessError(409, "INVALID_STATE", "Chỉ cấp lại QR cho phiên đang giữ ô/đang đỗ")
    at = core.now()
    return core.table("sessions").update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET claim_nonce = :n, claim_expires_at = :e, history = list_append(history, :h)",
        ExpressionAttributeValues={":n": secrets.token_urlsafe(16), ":e": core.iso(at + core.CLAIM_TTL),
                                   ":h": [_history(actor, "RENEW_CLAIM")]},
        ReturnValues="ALL_NEW",
    )["Attributes"]


# ── trạng thái ô từ ESP slots ──────────────────────────────────────────────


def apply_slot(slot_id, occupied, source, force=False):
    """Cập nhật tín hiệu hiện trường của một ô và suy ra trạng thái nghiệp vụ.

    Không bao giờ ghi đè RESERVED của backend bằng tín hiệu trống.
    """
    if slot_id not in core.SLOT_IDS:
        return
    if source != core.slot_source(slot_id):
        core.log.warning("slot %s sai source %s", slot_id, source)
        return
    at = core.iso(core.now())
    for _ in range(3):
        slot = core.table("slots").get_item(Key={"slot_id": slot_id}).get("Item") or {"slot_id": slot_id}
        old_status, old_occ = slot.get("status"), slot.get("occupied")
        if not force and old_occ == occupied and old_status != "UNKNOWN":
            return
        res_sid = slot.get("reserved_session_id")
        park_sid = None
        if old_status == "OUT_OF_SERVICE":
            status = "OUT_OF_SERVICE"
        elif occupied:
            status = "OCCUPIED"
            if res_sid:
                park_sid = res_sid
            elif old_status == "AVAILABLE":
                core.alert("WRONG_SLOT", f"Ô {slot_id} có xe nhưng không được gán cho lượt nào")
        else:
            status = "AVAILABLE"
            if res_sid:
                sess = core.table("sessions").get_item(Key={"session_id": res_sid}).get("Item")
                if sess and sess.get("state") == "RESERVED":
                    status = "RESERVED"
                else:
                    res_sid = None
        expr = "SET #st = :st, occupied = :occ, updated_at = :now, sensor_seen_at = :now, #src = :src"
        values = {":st": status, ":occ": occupied, ":now": at, ":src": source}
        if res_sid:
            expr += ", reserved_session_id = :sid"
            values[":sid"] = res_sid
        else:
            expr += " REMOVE reserved_session_id"
        cond = "attribute_not_exists(updated_at)" if "updated_at" not in slot else "updated_at = :old"
        if "updated_at" in slot:
            values[":old"] = slot["updated_at"]
        try:
            core.table("slots").update_item(
                Key={"slot_id": slot_id}, UpdateExpression=expr, ConditionExpression=cond,
                ExpressionAttributeNames={"#st": "status", "#src": "source"}, ExpressionAttributeValues=values,
            )
            break
        except Exception as err:  # noqa: BLE001
            if not core.is_conditional_failure(err):
                raise
    else:
        core.log.warning("slot %s update conflict", slot_id)
        return
    if park_sid:
        _mark_parked(park_sid, slot_id)


def _mark_parked(session_id, slot_id):
    try:
        core.table("sessions").update_item(
            Key={"session_id": session_id},
            ConditionExpression="#s = :r AND slot_id = :slot",
            UpdateExpression="SET #s = :p, parked_at = :at, history = list_append(history, :h)",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":r": "RESERVED", ":p": "PARKED", ":slot": slot_id,
                                       ":at": core.iso(core.now()), ":h": [_history(core.SLOTS_ID, "PARKED")]},
        )
    except Exception as err:  # noqa: BLE001
        if not core.is_conditional_failure(err):
            raise


def accept_slot_seq(msg):
    """Bỏ message cũ hơn trong cùng boot_id (MQTT có thể đảo thứ tự)."""
    boot, seq = msg.get("boot_id"), int(msg.get("seq") or 0)
    try:
        core.table("devices").update_item(
            Key={"device_id": core.SLOTS_ID},
            ConditionExpression="attribute_not_exists(slots_boot_id) OR slots_boot_id <> :b OR slots_seq < :q",
            UpdateExpression="SET slots_boot_id = :b, slots_seq = :q",
            ExpressionAttributeValues={":b": boot, ":q": seq},
        )
        return True
    except Exception as err:  # noqa: BLE001
        if core.is_conditional_failure(err):
            return False
        raise


def handle_slots(msg):
    if not accept_slot_seq(msg):
        return {"result": "STALE"}
    if msg["message_type"] == "slot_changed":
        apply_slot(msg["slot_id"], bool(msg["occupied"]), msg.get("source"))
    elif msg["message_type"] == "slots_snapshot":
        entries = {s["slot_id"]: s for s in msg.get("slots", [])}
        if set(entries) != set(core.SLOT_IDS):
            core.log.warning("snapshot thiếu/thừa ô: %d", len(entries))
        for slot_id, s in entries.items():
            apply_slot(slot_id, bool(s["occupied"]), s.get("source"))
    return {"result": "OK"}


# ── thiết bị ───────────────────────────────────────────────────────────────


def touch_device(device_id, msg):
    state = msg.get("state") if msg.get("message_type") == "device_status" else None
    expr = "SET last_seen_at = :now"
    values = {":now": core.iso(core.now())}
    if state:
        expr += ", #st = :st, firmware_version = :fw, boot_id = :boot"
        values.update({":st": state, ":fw": msg.get("firmware_version", "?"), ":boot": msg.get("boot_id", "?")})
    else:
        expr += ", #st = if_not_exists(#st, :online)"
        values[":online"] = "ONLINE"
    prev = core.table("devices").update_item(
        Key={"device_id": device_id}, UpdateExpression=expr,
        ExpressionAttributeNames={"#st": "state"}, ExpressionAttributeValues=values, ReturnValues="UPDATED_OLD",
    ).get("Attributes", {})
    if state == "OFFLINE":
        core.alert("DEVICE_OFFLINE", f"Thiết bị {device_id} báo mất kết nối (Last Will)")
    elif prev.get("state") == "OFFLINE" and state:
        core.alert("DEVICE_ONLINE", f"Thiết bị {device_id} đã kết nối lại", level="INFO")
    elif prev.get("state") == "OFFLINE":
        core.table("devices").update_item(
            Key={"device_id": device_id}, UpdateExpression="SET #st = :on",
            ExpressionAttributeNames={"#st": "state"}, ExpressionAttributeValues={":on": "ONLINE"},
        )


def handle_gate_telemetry(msg):
    gate, state, cmd_id = msg.get("gate"), msg.get("state"), msg.get("command_id")
    if gate in ("ENTRY", "EXIT"):
        core.table("devices").update_item(
            Key={"device_id": core.GATE_ID},
            UpdateExpression="SET gates = if_not_exists(gates, :empty)",
            ExpressionAttributeValues={":empty": {}},
        )
        core.table("devices").update_item(
            Key={"device_id": core.GATE_ID},
            UpdateExpression="SET gates.#g = :v",
            ExpressionAttributeNames={"#g": gate},
            ExpressionAttributeValues={":v": {"state": state, "command_id": cmd_id, "error_code": msg.get("error_code"),
                                              "at": msg.get("occurred_at")}},
        )
    if cmd_id and state in ("OPENING", "OPEN", "CLOSING", "CLOSED", "ERROR"):
        try:
            core.table("devices").update_item(
                Key={"device_id": core.GATE_ID},
                UpdateExpression="REMOVE pending_commands.#c",
                ConditionExpression="attribute_exists(pending_commands.#c)",
                ExpressionAttributeNames={"#c": cmd_id},
            )
        except Exception as err:  # noqa: BLE001
            if not core.is_conditional_failure(err):
                raise
    if state == "ERROR" and msg.get("error_code") not in ("DUPLICATE_COMMAND",):
        core.alert("GATE_ERROR", f"Cần {gate} báo lỗi {msg.get('error_code')}", level="ERROR")
    return {"result": "OK"}


def handle_display_telemetry(msg):
    core.table("devices").update_item(
        Key={"device_id": core.GATE_ID},
        UpdateExpression="SET display = :d",
        ExpressionAttributeValues={":d": {"state": msg.get("state"), "command_id": msg.get("command_id"),
                                          "screen": msg.get("screen"), "at": msg.get("occurred_at")}},
    )
    return {"result": "OK"}
