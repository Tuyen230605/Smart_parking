"""Chạy backend trên máy, không cần AWS: HTTP API cho web, nhận/phát MQTT qua Mosquitto local.

    cd backend
    uv run python local/dev_server.py                          # API http://localhost:3001/v1
    uv run python local/dev_server.py --mqtt localhost:1883    # nhận sự kiện mock_pi/mock thiết bị, phát lệnh cổng
    uv run python local/dev_server.py --fake-slots             # giả slots-01: snapshot mỗi 30 giây

Web: đặt VITE_API_BASE_URL=http://localhost:3001/v1 trong web/.env.local. Mọi request được coi như đã đăng nhập
nhóm ADMIN và KIOSK (đổi bằng --groups). Dữ liệu trong RAM (DynamoDB giả bằng moto), mất khi tắt; email chỉ in
ra màn hình. Chỉ dùng khi phát triển.

Endpoint riêng cho phát triển:
    POST /dev/mqtt           body là message MQTT v1 kèm "mqtt_topic", xử lý như IoT Rule
    POST /dev/slots/F1-A2    body {"occupied": true}, giả slot_changed từ slots-01
    POST /dev/jobs/expire_reservations | /dev/jobs/purge_identity   chạy job ngay
"""
import argparse
import itertools
import json
import os
import re
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
for _name, _value in {"AWS_ACCESS_KEY_ID": "local", "AWS_SECRET_ACCESS_KEY": "local",
                      "AWS_DEFAULT_REGION": "ap-southeast-2"}.items():
    os.environ.setdefault(_name, _value)

from parking import api, ingest, jobs  # noqa: E402
from parking.app import App  # noqa: E402
from parking.claims import KeyRing  # noqa: E402
from parking.config import Config  # noqa: E402
from parking.contract import SLOTS  # noqa: E402
from parking.layout import SLOT_IDS, source_of  # noqa: E402
from parking.log import log  # noqa: E402
from parking.store import Db  # noqa: E402
from parking.timeutil import iso  # noqa: E402

CORS_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "Authorization, Content-Type, Idempotency-Key",
    "access-control-allow-methods": "GET, POST, PUT, OPTIONS",
}
SLOT_PATH_RE = re.compile(r"/dev/slots/(F[12]-[ABC][123])")
JOB_PATH_RE = re.compile(r"/dev/jobs/(\w+)")


class LogPublisher:
    def publish(self, topic, payload):
        log("local_publish", topic=topic, payload=payload)


class MqttPublisher:
    def __init__(self, client):
        self.client = client

    def publish(self, topic, payload):
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)


class ConsoleMailer:
    def send(self, to, subject, text):
        print(f"\n--- Email tới {to}: {subject}\n{text}---\n", flush=True)
        return f"local-{uuid.uuid4()}"


class LocalBackend:
    """Mọi lời gọi vào backend đi qua một khóa: HTTP, MQTT và job chạy ở các luồng khác nhau."""

    def __init__(self, app: App, groups=("ADMIN", "KIOSK")):
        self.app = app
        self.lock = threading.Lock()
        self.claims = {"cognito:groups": f"[{' '.join(groups)}]", "sub": "local-dev", "username": "local-dev"}
        self.slots_boot_id = str(uuid.uuid4())
        self._seq = itertools.count(1)

    def http(self, method: str, path: str, query: dict, headers: dict, body: str | None) -> dict:
        event = {
            "rawPath": path,
            "headers": headers,
            "queryStringParameters": query or None,
            "body": body,
            "isBase64Encoded": False,
            "requestContext": {"http": {"method": method}, "stage": "v1", "requestId": str(uuid.uuid4()),
                               "authorizer": {"jwt": {"claims": self.claims}}},
        }
        with self.lock:
            return api.handle(self.app, event)

    def device_message(self, message) -> str:
        with self.lock:
            return ingest.process(self.app, message)

    def run_job(self, name: str) -> dict:
        with self.lock:
            return jobs.JOBS[name](self.app)

    def _slots_message(self, message_type: str, **fields) -> dict:
        return {
            "mqtt_topic": f"parking/v1/{self.app.cfg.site_id}/slots/{SLOTS}/state",
            "schema_version": 1,
            "message_type": message_type,
            "event_id": str(uuid.uuid4()),
            "device_id": SLOTS,
            "boot_id": self.slots_boot_id,
            "seq": next(self._seq),
            "occurred_at": iso(self.app.clock()),
            **fields,
        }

    def set_slot(self, slot_id: str, occupied: bool) -> str:
        return self.device_message(self._slots_message("slot_changed", slot_id=slot_id, occupied=occupied,
                                                       source=source_of(slot_id)))

    def fake_snapshot(self) -> str:
        """Snapshot đủ 18 ô, giữ trạng thái có xe hiện tại để không xóa thay đổi từ /dev/slots."""
        with self.lock:
            current = {s["slot_id"]: s for s in self.app.db.batch_get(
                self.app.cfg.tables.slots, [{"slot_id": sid} for sid in SLOT_IDS])}
        slots = [{"slot_id": sid, "occupied": bool(current.get(sid, {}).get("occupied")), "source": source_of(sid)}
                 for sid in SLOT_IDS]
        return self.device_message(self._slots_message("slots_snapshot", slots=slots))


def make_server(backend: LocalBackend, host: str, port: int) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, status: int, body: str = "", headers: dict | None = None):
            data = body.encode()
            self.send_response(status)
            for name, value in {**CORS_HEADERS, **(headers or {})}.items():
                self.send_header(name, value)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, payload):
            self._send(status, json.dumps(payload, ensure_ascii=False), {"content-type": "application/json"})

        def _body(self) -> str | None:
            length = int(self.headers.get("content-length") or 0)
            return self.rfile.read(length).decode() if length else None

        def do_OPTIONS(self):
            self._send(204)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def _dispatch(self, method: str):
            url = urlparse(self.path)
            body = self._body()
            try:
                if url.path.startswith("/v1/"):
                    query = {k: v[0] for k, v in parse_qs(url.query).items()}
                    headers = {k.lower(): v for k, v in self.headers.items()}
                    result = backend.http(method, url.path, query, headers, body)
                    return self._send(result["statusCode"], result["body"], result["headers"])
                if method != "POST":
                    return self._json(404, {"code": "NOT_FOUND", "message": "Không có endpoint này"})
                if url.path == "/dev/mqtt":
                    return self._json(200, {"outcome": backend.device_message(json.loads(body or "null"))})
                if m := SLOT_PATH_RE.fullmatch(url.path):
                    occupied = json.loads(body or "{}").get("occupied")
                    if type(occupied) is not bool:
                        return self._json(400, {"code": "INVALID_INPUT", "message": "Cần {\"occupied\": true|false}"})
                    return self._json(200, {"outcome": backend.set_slot(m[1], occupied)})
                if (m := JOB_PATH_RE.fullmatch(url.path)) and m[1] in jobs.JOBS:
                    return self._json(200, backend.run_job(m[1]))
                self._json(404, {"code": "NOT_FOUND", "message": "Không có endpoint này"})
            except (ValueError, AttributeError) as e:
                self._json(400, {"code": "INVALID_INPUT", "message": str(e)})

    return HTTPServer((host, port), Handler)


def _every(seconds: float, fn, name: str):
    def loop():
        while True:
            try:
                fn()
            except Exception as e:
                log("local_task_failed", task=name, error=repr(e))
            time.sleep(seconds)
    threading.Thread(target=loop, name=name, daemon=True).start()


def _connect_mqtt(address: str):
    import paho.mqtt.client as mqtt

    host, _, port = address.partition(":")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"local-backend-{uuid.uuid4().hex[:6]}")
    client.connect(host, int(port or 1883))
    return client


def _bridge_mqtt(client, backend: LocalBackend):
    """Nhận mọi topic thiết bị của site (trừ lệnh do chính backend phát) và xử lý như IoT Rule."""
    site = backend.app.cfg.site_id

    def on_connect(c, _userdata, _flags, reason_code, _properties):
        c.subscribe(f"parking/v1/{site}/+/+/+", qos=1)
        log("local_mqtt_connected", reason=str(reason_code))

    def on_message(_c, _userdata, msg):
        if msg.topic.endswith("/commands"):
            return
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            log("local_mqtt_bad_json", topic=msg.topic)
            return
        if isinstance(payload, dict):
            payload["mqtt_topic"] = msg.topic
        try:
            backend.device_message(payload)
        except Exception as e:
            log("local_mqtt_failed", topic=msg.topic, error=repr(e))

    client.on_connect = on_connect
    client.on_message = on_message
    client.loop_start()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 để máy khác trong LAN gọi được")
    p.add_argument("--port", type=int, default=3001)
    p.add_argument("--web", default="http://localhost:5173", help="URL web để tạo link QR")
    p.add_argument("--mqtt", metavar="HOST:PORT", help="nối Mosquitto, ví dụ localhost:1883")
    p.add_argument("--fake-slots", action="store_true", help="tự gửi snapshot slots-01 mỗi 30 giây")
    p.add_argument("--groups", default="ADMIN,KIOSK", help="nhóm Cognito giả cho mọi request")
    args = p.parse_args()

    import boto3
    from moto import mock_aws

    from schema import LOCAL_TABLES, create_tables

    with mock_aws():
        client = boto3.client("dynamodb")
        create_tables(client)
        key = secrets.token_urlsafe(36)
        cfg = Config(site_id="site-01", tables=LOCAL_TABLES, web_base_url=args.web.rstrip("/"), claim_keys=key)
        mqtt_client = _connect_mqtt(args.mqtt) if args.mqtt else None
        publisher = MqttPublisher(mqtt_client) if mqtt_client else LogPublisher()
        app = App(cfg, Db(client), publisher, ConsoleMailer(), KeyRing(lambda: key))
        backend = LocalBackend(app, tuple(g for g in args.groups.split(",") if g))
        if mqtt_client:
            _bridge_mqtt(mqtt_client, backend)
        if args.fake_slots:
            _every(30, backend.fake_snapshot, "fake-slots")
        _every(60, lambda: backend.run_job("expire_reservations"), "expire-reservations")
        _every(3600, lambda: backend.run_job("purge_identity"), "purge-identity")

        server = make_server(backend, args.host, args.port)
        print(f"API local: http://{args.host}:{args.port}/v1  (VITE_API_BASE_URL)", flush=True)
        print(f"MQTT: {args.mqtt or 'tắt, lệnh cổng chỉ in log'} · slots-01 giả: {'bật' if args.fake_slots else 'tắt'}",
              flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            if mqtt_client:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()


if __name__ == "__main__":
    main()
