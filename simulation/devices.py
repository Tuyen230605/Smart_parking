"""Kết nối MQTT dùng chung cho mock thiết bị: cùng client id, cert, topic và schema với thiết bị thật.

Mặc định nối AWS IoT Core bằng secrets/iot.json + secrets/certs/<device>/ (do provision-devices.sh sinh).
--local: nối Mosquitto localhost:1883 không TLS để thử offline.
IOT_PORT=443: dùng khi mạng chặn cổng 8883.

LƯU Ý: AWS IoT chỉ cho MỘT kết nối mỗi client id. Khi đã nạp ESP32 thật, tắt mock tương ứng.
"""
import itertools
import json
import logging
import os
import ssl
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

REPO = Path(__file__).resolve().parents[1]
SITE = "site-01"
log = logging.getLogger("mock")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def topic(kind, device_id, leaf):
    return f"parking/v1/{SITE}/{kind}/{device_id}/{leaf}"


class Device:
    def __init__(self, device_id, firmware_version="mock-1.0", local=False, subscriptions=(), on_message=None,
                 on_connect=None):
        self.device_id = device_id
        self.firmware_version = firmware_version
        self.boot_id = str(uuid.uuid4())
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self.subscriptions = list(subscriptions)
        self.user_on_message = on_message
        self.user_on_connect = on_connect
        self.connected = threading.Event()
        self.status_topic = topic("devices", device_id, "status")

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=device_id)
        if local:
            host, port = "localhost", 1883
        else:
            cfg_path = REPO / "secrets" / "iot.json"
            if not cfg_path.exists():
                raise SystemExit("Chưa có secrets/iot.json — chạy infra/aws/provision-devices.sh trước (hoặc dùng --local)")
            cfg = json.loads(cfg_path.read_text())
            certs = Path(cfg["certs_dir"])
            port = int(os.environ.get("IOT_PORT", "8883"))
            ctx = ssl.create_default_context(cafile=str(certs / "AmazonRootCA1.pem"))
            ctx.load_cert_chain(str(certs / device_id / "cert.pem"), str(certs / device_id / "private.key"))
            if port == 443:  # mạng chặn 8883 → MQTT qua 443 với ALPN
                ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])
            self.client.tls_set_context(ctx)
            host = cfg["endpoint"]
        will = self.envelope("device_status") | {"state": "OFFLINE", "firmware_version": firmware_version}
        self.client.will_set(self.status_topic, json.dumps(will), qos=1)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 30)
        self.host, self.port = host, port

    def start(self):
        log.info("Kết nối %s:%s với client id %s", self.host, self.port, self.device_id)
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()
        if not self.connected.wait(15):
            log.warning("Chưa kết nối được sau 15 giây (sai cert/endpoint/policy? Mạng?) — vẫn đang thử lại")
        return self

    def stop(self):
        self._stopping = True
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Bị từ chối kết nối: %s", reason_code)
            return
        log.info("✓ Đã kết nối MQTT")
        for t in self.subscriptions:
            client.subscribe(t, qos=1)
        self.connected.set()
        self.status()
        if self.user_on_connect:
            self.user_on_connect()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        if not getattr(self, "_stopping", False):
            log.warning("Mất kết nối MQTT (%s), đang thử lại…", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            log.warning("Bỏ message không phải JSON trên %s", msg.topic)
            return
        if self.user_on_message:
            self.user_on_message(msg.topic, payload)

    def envelope(self, message_type):
        with self._lock:
            seq = next(self._seq)
        return {"schema_version": 1, "message_type": message_type, "event_id": str(uuid.uuid4()),
                "device_id": self.device_id, "boot_id": self.boot_id, "seq": seq, "occurred_at": utc_now()}

    def publish(self, t, payload, quiet=False):
        body = json.dumps(payload, ensure_ascii=False)
        if not quiet:
            log.info("→ %s %s", t.split("/", 3)[-1], body if len(body) < 220 else body[:220] + "…")
        self.client.publish(t, body, qos=1, retain=False)

    def status(self, state="ONLINE"):
        self.publish(self.status_topic, self.envelope("device_status") | {
            "state": state, "firmware_version": self.firmware_version}, quiet=True)

    def every(self, seconds, fn):
        """Gọi fn mỗi `seconds` giây trên thread nền (chỉ khi đang kết nối)."""
        def loop():
            stop = threading.Event()
            while not stop.wait(seconds):
                if self.connected.is_set():
                    fn()
        threading.Thread(target=loop, daemon=True).start()


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
