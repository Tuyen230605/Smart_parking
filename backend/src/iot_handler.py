"""Lambda nhận message thiết bị từ IoT Rule.

SQL rule: SELECT *, topic() AS mqtt_topic FROM 'parking/v1/site-01/#'
          WHERE message_type <> 'gate_command' AND message_type <> 'display_command'
"""
import core
import logic

# (loại topic, device id trong topic) → handler; khớp docs/mqtt-contract.md
ROUTES = {
    ("vision", "events", core.PI_ID): ("vehicle_detected", logic.handle_vehicle_detected),
    ("slots", "state", core.SLOTS_ID): (("slot_changed", "slots_snapshot"), logic.handle_slots),
    ("gates", "telemetry", core.GATE_ID): ("gate_telemetry", logic.handle_gate_telemetry),
    ("displays", "telemetry", core.GATE_ID): ("display_telemetry", logic.handle_display_telemetry),
}


def handler(event, _context):
    topic = event.pop("mqtt_topic", "")
    parts = topic.split("/")
    # parking/v1/<site>/<kind>/<device>/<leaf>
    if len(parts) != 6 or parts[:3] != ["parking", "v1", core.SITE_ID]:
        core.log.warning("bỏ topic lạ: %s", topic)
        return {"result": "IGNORED"}
    kind, device_id, leaf = parts[3], parts[4], parts[5]
    msg_type = event.get("message_type")
    if event.get("schema_version") != 1:
        core.log.warning("schema_version không hỗ trợ trên %s", topic)
        return {"result": "SCHEMA_UNSUPPORTED"}
    # Policy IoT đã giới hạn ai publish topic nào; vẫn kiểm tra device_id trong payload khớp topic.
    if event.get("device_id") not in (None, device_id):
        core.log.warning("device_id không khớp topic %s", topic)
        return {"result": "IGNORED"}

    if kind == "devices" and leaf == "status":
        if device_id not in core.DEVICES or msg_type != "device_status":
            return {"result": "IGNORED"}
        logic.touch_device(device_id, event)
        return {"result": "OK"}

    route = ROUTES.get((kind, leaf, device_id))
    if not route:
        core.log.warning("không có route cho %s", topic)
        return {"result": "IGNORED"}
    expected, fn = route
    if msg_type not in (expected if isinstance(expected, tuple) else (expected,)):
        core.log.warning("message_type %s sai trên %s", msg_type, topic)
        return {"result": "IGNORED"}
    logic.touch_device(device_id, event)
    core.log.info("in %s %s", msg_type, event.get("event_id") or event.get("command_id"))
    return fn(event)
