"""Publish `vehicle_detected` và `device_status` theo MQTT v1 (docs/mqtt-contract.md)."""
import itertools
import json
import logging
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Publisher:
    def __init__(self, device_cfg, mqtt_cfg, dry_run=False):
        self.device_id = device_cfg["device_id"]
        self.firmware_version = device_cfg["firmware_version"]
        site = device_cfg["site_id"]
        self.events_topic = f"parking/v1/{site}/vision/{self.device_id}/events"
        self.status_topic = f"parking/v1/{site}/devices/{self.device_id}/status"
        self.boot_id = str(uuid.uuid4())
        self._seq = itertools.count(1)
        self.client = None
        if dry_run or not mqtt_cfg["enabled"]:
            log.info("MQTT tắt: chỉ in message ra log")
            return
        self._connect(mqtt_cfg)

    def _connect(self, cfg):
        import paho.mqtt.client as mqtt

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.device_id)
        if cfg["tls"]:
            self.client.tls_set(ca_certs=cfg["ca_cert"], certfile=cfg["cert"], keyfile=cfg["key"])
        will = self._envelope("device_status") | {"state": "OFFLINE", "firmware_version": self.firmware_version}
        self.client.will_set(self.status_topic, json.dumps(will), qos=1, retain=False)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = lambda *a: log.warning("Mất kết nối MQTT, đang thử lại")
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.connect_async(cfg["host"], cfg["port"], keepalive=60)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("MQTT từ chối kết nối: %s", reason_code)
            return
        log.info("Đã kết nối MQTT")
        self.status()

    def _envelope(self, message_type):
        return {
            "schema_version": 1,
            "message_type": message_type,
            "event_id": str(uuid.uuid4()),
            "device_id": self.device_id,
            "boot_id": self.boot_id,
            "seq": next(self._seq),
            "occurred_at": utc_now(),
        }

    def _publish(self, topic, payload):
        body = json.dumps(payload, ensure_ascii=False)
        log.info("%s %s", topic, body)
        if self.client:
            self.client.publish(topic, body, qos=1, retain=False)
        return payload

    def vehicle_detected(self, lane_id, card_color, plate_text, plate_confidence):
        return self._publish(self.events_topic, self._envelope("vehicle_detected") | {
            "lane_id": lane_id,
            "card_color": card_color,
            "plate_text": plate_text,
            "plate_confidence": plate_confidence,
        })

    def status(self, state="ONLINE"):
        return self._publish(self.status_topic, self._envelope("device_status") | {
            "state": state,
            "firmware_version": self.firmware_version,
        })

    def close(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
