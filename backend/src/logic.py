"""Nghiệp vụ bãi xe: vào/ra có quản trị cho phép, tính phí, trạng thái ô, duyệt thủ công.

Trạng thái phiên:
  camera thấy xe vào → ENTRY_PENDING → (admin "Cho vào": mở cần vào) PARKED | REJECTED
  camera thấy xe ra  → EXIT_REQUESTED (khóa phí) → (admin "Cho ra": mở cần ra) CLOSED
  MANUAL_REVIEW (biển/làn bất thường) → (admin) PARKED | RESOLVED | REJECTED
  Không gán ô: nút ô chỉ để chỉ chỗ trống; phiên và tiền chỉ theo camera + quản trị + cần chắn.
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
    """Camera chỉ báo "có xe" ở làn; mọi lượt vào/ra đều chờ quản trị bấm cho phép trên trang Phiên đỗ.

    Pi demo không đọc biển: plate_text rỗng → backend tự đánh biển demo (11111, 22222…) khi vào,
    và chọn xe có số lớn nhất đang trong bãi khi ra.
    """
    event_id = msg["event_id"]
    if core.already_processed(event_id):
        return {"result": "DUPLICATE"}
    lane, color = msg.get("lane_id"), msg.get("card_color")
    plate, conf = msg.get("plate_text"), float(msg.get("plate_confidence") or 0)
    if (lane, color) not in (("ENTRY", "GREEN"), ("EXIT", "RED")):
        core.mark_processed(event_id, "vehicle_detected")
        core.log.warning("bỏ sự kiện sai làn %s+%s", lane, color)
        return {"result": "IGNORED"}
    readable = bool(core.plate_key(plate)) and conf >= core.PLATE_THRESHOLD

    if lane == "ENTRY":
        if not readable:
            plate, conf = next_demo_plate(), 1.0
        return request_entry(plate, conf, event_id)

    if readable:
        return request_exit(plate, conf, event_id=event_id, actor=core.PI_ID)
    car = newest_car()
    if not car:
        core.mark_processed(event_id, "vehicle_detected")
        core.log.info("làn RA thấy xe nhưng bãi không còn xe nào chưa yêu cầu ra")
        return {"result": "NO_CAR"}
    return request_exit(car["plate_display"], 1.0, event_id=event_id, actor=core.PI_ID)


def _sessions_in(states):
    names = {"#s": "state"}
    values = {f":s{i}": st for i, st in enumerate(states)}
    return core.scan_all("sessions", FilterExpression="#s IN (" + ", ".join(values) + ")",
                         ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def next_demo_plate():
    """Số nhỏ nhất chưa dùng bởi xe trong bãi hoặc xe đang chờ vào."""
    used = {s.get("plate_normalized") for s in _sessions_in(core.IN_LOT_STATES + ("ENTRY_PENDING",))}
    k = 1
    while core.demo_plate(k) in used:
        k += 1
    return core.demo_plate(k)


def _car_order(s):
    return (core.demo_number(s.get("plate_display")) or 0, s.get("checkin_at") or "")


def newest_car():
    """Xe ra tiếp theo: số lớn nhất trong các xe đang đỗ (chưa yêu cầu ra)."""
    cars = [s for s in _sessions_in(("RESERVED", "PARKED")) if s.get("plate_display")]
    return max(cars, key=_car_order) if cars else None


def request_entry(plate, conf, event_id):
    """Ghi lượt "chờ cho vào"; quản trị bấm Cho vào mới mở cần và tính là xe trong bãi."""
    if event_id and not core.mark_processed(event_id, "vehicle_detected"):
        return {"result": "DUPLICATE"}
    at = core.now()
    session = {
        "session_id": core.ulid(),
        "session_ref": core.short_ref(),
        "state": "ENTRY_PENDING",
        "review_lane": "ENTRY",
        "created_at": core.iso(at),
        "history": [_history(core.PI_ID, "ENTRY_DETECTED")],
        **_identity_fields(plate, conf, at),
    }
    core.table("sessions").put_item(Item=session)
    core.alert("ENTRY_PENDING", f"Xe {plate} (lượt {session['session_ref']}) chờ cho vào", level="INFO",
               session_id=session["session_id"])
    services.display_command("ENTRY_ROUTE", [f"XE {plate}", "Cho nhan vien", "cho phep vao"])
    publish_lot()
    return {"result": "ENTRY_PENDING", "session_id": session["session_id"], "plate": plate}


def auto_email(session_id, key):
    """Biển số đã được khách liên kết email → tự gửi chỉ dẫn, không cần quét QR."""
    link = core.table("plate_emails").get_item(Key={"plate_normalized": key}).get("Item") if key else None
    if not link:
        return False
    session = get_session(session_id)
    at = core.iso(core.now())
    try:
        mid = services.send_guide_email(link["email"], session,
                                        unsubscribe=services.unsubscribe_url(key, link["nonce"]))
        expr, values = "SET email_status = :st, ses_message_id = :m, email_auto = :t, email_collected_at = :at", \
            {":st": "ACCEPTED_BY_SES", ":m": mid or "-", ":t": True, ":at": at}
    except Exception as err:  # noqa: BLE001 — lỗi SES không chặn xe vào
        core.alert("EMAIL_FAILED", f"Không tự gửi được email cho lượt {session['session_ref']} ({type(err).__name__})",
                   session_id=session_id)
        expr, values = "SET email_status = :st, email_error = :r", {":st": "FAILED", ":r": type(err).__name__}
    core.table("sessions").update_item(Key={"session_id": session_id}, UpdateExpression=expr,
                                       ExpressionAttributeValues=values)
    return True


def lot_state():
    """Danh sách xe trong bãi + xe chờ vào/chờ ra, sắp theo số xe (nguồn duy nhất cho web và Pi)."""
    sessions = sorted(_sessions_in(core.IN_LOT_STATES + ("ENTRY_PENDING",)), key=_car_order)

    def view(s):
        return {"plate": s.get("plate_display"), "session_id": s["session_id"], "session_ref": s.get("session_ref"),
                "state": s["state"], "checkin_at": s.get("checkin_at")}

    return {
        "in_lot": [view(s) for s in sessions if s["state"] in core.IN_LOT_STATES],
        "pending_entry": [view(s) for s in sessions if s["state"] == "ENTRY_PENDING"],
        "pending_exit": [view(s) for s in sessions if s["state"] == "EXIT_REQUESTED"],
    }


def publish_lot():
    """Gửi danh sách xe xuống Pi (trang camera hiển thị). Lỗi gửi không làm hỏng nghiệp vụ."""
    state = lot_state()
    try:
        services.mqtt_publish(f"parking/v1/{core.SITE_ID}/vision/{core.PI_ID}/{core.LOT_TOPIC_LEAF}", {
            "schema_version": 1, "message_type": "lot_state", "occurred_at": core.iso(core.now()),
            "in_lot": [c["plate"] for c in state["in_lot"]],
            "pending_entry": [c["plate"] for c in state["pending_entry"]],
            "pending_exit": [c["plate"] for c in state["pending_exit"]],
        })
    except Exception as err:  # noqa: BLE001
        core.log.warning("không gửi được lot_state: %s", err)
    return state


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


def free_slots():
    """Ô đang trống theo thứ tự gần cổng trước; None nếu board ô offline (không biết ô nào trống)."""
    if not services.device_online(core.SLOTS_ID):
        return None
    slots = {s["slot_id"]: s for s in core.scan_all("slots")}
    return [sid for sid in core.SLOT_IDS if slots.get(sid, {}).get("status") == "AVAILABLE"]


def suggestion():
    """Gợi ý chỉ đường (KHÔNG gán ô): ô trống gần cổng nhất lúc hỏi và số ô còn trống."""
    free = free_slots()
    if free is None:
        return {"slot_id": None, "free_count": None}
    return {"slot_id": free[0] if free else None, "free_count": len(free)}


def entry(plate, conf, event_id=None, actor="system", review_session=None, reason=None):
    """Tạo phiên + khóa biển số trong một transaction rồi mở cần vào.

    Không gán ô: nút/cảm biến ô chỉ dùng để chỉ chỗ trống, không liên quan phiên hay tiền.
    Chỉ từ chối khi board ô đang online và báo không còn ô trống nào (bãi đầy).
    """
    key = core.plate_key(plate)
    at = core.now()
    free = free_slots()
    if free is not None and not free:
        if event_id and not core.mark_processed(event_id, "vehicle_detected"):
            return {"result": "DUPLICATE"}
        services.display_command("LOT_FULL", ["BAI DA DAY", "Xin loi quy khach", "Vui long quay lai"])
        core.alert("LOT_FULL", "Xe yêu cầu vào nhưng không còn ô trống", level="INFO")
        if review_session:
            raise BusinessError(409, "SLOT_CONFLICT", "Bãi đã đầy")
        return {"result": "LOT_FULL"}

    base = {
        "state": "PARKED",
        "checkin_at": core.iso(at),
        "claim_nonce": secrets.token_urlsafe(16),  # 128 bit
        "claim_expires_at": core.iso(at + core.CLAIM_TTL),
        "pricing": services.current_pricing(),
        **_identity_fields(plate, conf, at),
    }
    if review_session:
        session_id, session_ref = review_session["session_id"], review_session["session_ref"]
        fields = {**base, "resolved_by": actor}
        values = {f":{k}": v for k, v in fields.items()}
        values[":review"] = "MANUAL_REVIEW"
        values[":pending"] = "ENTRY_PENDING"
        values[":h"] = [_history(actor, "ALLOW_ENTRY", reason)]
        items = [{"Update": {
            "TableName": core.table_name("sessions"),
            "Key": {"session_id": session_id},
            "ConditionExpression": "#state IN (:review, :pending)",
            "UpdateExpression": "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
                                + ", history = list_append(history, :h)",
            "ExpressionAttributeNames": {f"#{k}": k for k in fields},
            "ExpressionAttributeValues": values,
        }}]
    else:
        session_id, session_ref = core.ulid(), core.short_ref()
        items = [{"Put": {
            "TableName": core.table_name("sessions"),
            "ConditionExpression": "attribute_not_exists(session_id)",
            "Item": {"session_id": session_id, "session_ref": session_ref, "created_at": core.iso(at),
                     "history": [_history(actor, "ENTRY")], **base},
        }}]
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
        if len(codes) > 2 and codes[2] == "ConditionalCheckFailed":
            return {"result": "DUPLICATE"}
        if codes[1] == "ConditionalCheckFailed":
            if review_session:
                raise BusinessError(409, "INVALID_STATE", "Biển số này đang có phiên mở") from err
            return create_review("ENTRY", plate, conf, "PLATE_ALREADY_ACTIVE", event_id)
        if review_session:
            raise BusinessError(409, "INVALID_STATE", "Phiên không còn ở trạng thái chờ duyệt") from err
        raise
    core.log.info("session %s entered", session_id)
    services.gate_command("ENTRY", "OPEN", session_id)
    hint = free[0] if free else None
    services.display_command("ENTRY_ROUTE", core.oled_hint(hint, len(free) if free is not None else None))
    if not services.device_online(core.GATE_ID):
        core.alert("DEVICE_OFFLINE", f"Lượt {session_ref} đã vào nhưng ESP cổng đang offline", session_id=session_id)
    auto_email(session_id, key)
    publish_lot()
    return {"result": "PARKED", "session_id": session_id, "suggested_slot": hint}


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
            if event_id:
                core.mark_processed(event_id, "vehicle_detected")
            return {"result": "NO_CAR"}
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
    # Không tự mở cần ra (kể cả miễn phí): quản trị xem phí trên trang Phiên đỗ rồi bấm cho ra.
    what = "miễn phí" if fee == 0 else f"thu {services.format_vnd(fee)} ₫"
    core.alert("PAYMENT_PENDING", f"Xe {session.get('plate_display', '')} (lượt {session['session_ref']}) chờ cho ra: {what}",
               level="INFO", session_id=session["session_id"])
    publish_lot()
    return {"result": "EXIT_REQUESTED", "session_id": session["session_id"], "fee_vnd": fee}


def _show_fee(session):
    fee = int(session.get("fee_vnd") or 0)
    if session.get("state") == "EXIT_OPENED":
        third = "Moi ra"
    else:
        third = "Cho nhan vien" if fee == 0 else "Moi thanh toan"
    services.display_command("EXIT_FEE", [f"RA: luot {session.get('session_ref', '?')}", f"Phi: {fee} VND", third])


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
    """Quản trị bấm Cho ra: mở cần RA và kết thúc phiên ngay (xe rời danh sách xe trong bãi)."""
    session = get_session(session_id)
    if session["state"] not in ("EXIT_REQUESTED", "EXIT_OPENED"):
        raise BusinessError(409, "INVALID_STATE", "Phiên chưa yêu cầu ra")
    if session.get("payment_status") not in ("NO_CHARGE", "PAID_CASH", "WAIVED"):
        raise BusinessError(409, "INVALID_STATE", "Chưa ghi nhận thu tiền")
    if not services.device_online(core.GATE_ID):
        raise BusinessError(503, "DEVICE_OFFLINE", "ESP cổng đang offline, không thể mở cần an toàn")
    cmd = services.gate_command("EXIT", "OPEN", session_id)
    at = core.iso(core.now())
    session = core.table("sessions").update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :closed, exit_opened_at = :at, exit_confirmed_at = :at, exit_command_id = :cmd, "
                         "history = list_append(history, :h) REMOVE claim_nonce, email",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":closed": "CLOSED", ":at": at, ":cmd": cmd["command_id"],
                                   ":h": [_history(actor, "OPEN_EXIT", cmd["command_id"])]},
        ReturnValues="ALL_NEW",
    )["Attributes"]
    release_plate(session)
    services.display_command("EXIT_FEE", [f"RA: luot {session.get('session_ref', '?')}",
                                          f"Phi: {int(session.get('fee_vnd') or 0)} VND", "Moi ra"])
    publish_lot()
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
    if session["state"] not in ("MANUAL_REVIEW", "ENTRY_PENDING"):
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
        publish_lot()
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
        raise BusinessError(409, "INVALID_STATE", "Chỉ cấp lại QR cho phiên đang trong bãi")
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
    """Cập nhật trạng thái một ô từ nút bấm: chỉ để chỉ chỗ trống, không đụng tới phiên."""
    if slot_id not in core.SLOT_IDS:
        return
    if source != core.slot_source(slot_id):
        core.log.warning("slot %s sai source %s", slot_id, source)
        return
    slot = core.table("slots").get_item(Key={"slot_id": slot_id}).get("Item") or {}
    if slot.get("status") == "OUT_OF_SERVICE":
        status = "OUT_OF_SERVICE"
    else:
        status = "OCCUPIED" if occupied else "AVAILABLE"
    if not force and slot.get("status") == status and slot.get("occupied") == occupied:
        return
    at = core.iso(core.now())
    core.table("slots").update_item(
        Key={"slot_id": slot_id},
        UpdateExpression="SET #st = :st, occupied = :occ, updated_at = :now, sensor_seen_at = :now, #src = :src "
                         "REMOVE reserved_session_id",
        ExpressionAttributeNames={"#st": "status", "#src": "source"},
        ExpressionAttributeValues={":st": status, ":occ": occupied, ":now": at, ":src": source},
    )


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
