"""API local (local/dev_server.py) chuyển request HTTP thành event API Gateway và có endpoint giả thiết bị."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from dev_server import LocalBackend, make_server

from conftest import vehicle


@pytest.fixture
def base_url(app):
    backend = LocalBackend(app)
    server = make_server(backend, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    backend.fake_snapshot()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def request(url, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, dict(r.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read().decode() or "null")


def test_local_server_end_to_end(app, base_url):
    assert request(f"{base_url}/dev/mqtt", "POST", vehicle(app))[2] == {"outcome": "RESERVED:F1-A1"}
    status, headers, claims = request(f"{base_url}/v1/kiosk/active-claims")
    assert status == 200 and claims[0]["slot_id"] == "F1-A1"
    assert headers["access-control-allow-origin"] == "*"

    assert request(f"{base_url}/dev/slots/F1-A1", "POST", {"occupied": True})[2] == {"outcome": "PARKED:F1-A1"}
    layout = {s["slot_id"]: s["status"] for s in request(f"{base_url}/v1/public/layout")[2]["slots"]}
    assert layout["F1-A1"] == "OCCUPIED" and layout["F1-A2"] == "AVAILABLE"

    status, _, page = request(f"{base_url}/v1/admin/sessions?status=PARKED&limit=5")
    assert status == 200 and len(page["sessions"]) == 1
    assert request(f"{base_url}/dev/jobs/expire_reservations", "POST")[2] == {"expired": 0, "parked": 0, "skipped": 0}


def test_local_server_cors_and_errors(base_url):
    status, headers, _ = request(f"{base_url}/v1/public/layout", "OPTIONS")
    assert status == 204 and "Idempotency-Key" in headers["access-control-allow-headers"]
    assert request(f"{base_url}/nope")[0] == 404
    assert request(f"{base_url}/dev/slots/F1-A2", "POST", {"occupied": "yes"})[0] == 400
    assert request(f"{base_url}/dev/mqtt", "POST", {"mqtt_topic": "x"})[2]["outcome"].startswith("INVALID")
