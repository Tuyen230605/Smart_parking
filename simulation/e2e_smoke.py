"""Kiểm thử đầu cuối trên AWS thật: xe vào → (đỗ) → xe ra miễn phí → xác nhận qua cổng → đóng phiên.

Cần: mock_gate.py và mock_slots.py (hoặc ESP thật) đang chạy, đã ./create-users.sh.
Script mượn client id pi-01 để gửi sự kiện camera → TẮT pi-vision trên Pi trước khi chạy.

    python simulation/e2e_smoke.py                       # hỏi mật khẩu admin
    ADMIN_PASSWORD=... python simulation/e2e_smoke.py --park-wait 0
"""
import argparse
import getpass
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

from devices import REPO, Device, setup_logging, topic


def load_env():
    env_file = REPO / "web" / ".env.production.local"
    if not env_file.exists():
        sys.exit("Chưa có web/.env.production.local — chạy infra/aws/deploy.sh trước")
    return dict(line.split("=", 1) for line in env_file.read_text().split() if "=" in line)


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json",
                                                                         **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def login(region, client_id, username, password):
    req = urllib.request.Request(
        f"https://cognito-idp.{region}.amazonaws.com/", method="POST",
        data=json.dumps({"AuthFlow": "USER_PASSWORD_AUTH", "ClientId": client_id,
                         "AuthParameters": {"USERNAME": username, "PASSWORD": password}}).encode(),
        headers={"Content-Type": "application/x-amz-json-1.1",
                 "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read())["AuthenticationResult"]["AccessToken"]
    except urllib.error.HTTPError as err:
        sys.exit(f"Đăng nhập thất bại: {err.read().decode()}")


def step(text):
    print(f"\n▶ {text}")


def ok(cond, text):
    print(f"  {'✓' if cond else '✗'} {text}")
    if not cond:
        sys.exit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user", default="admin")
    p.add_argument("--park-wait", type=int, default=45, help="số giây chờ bạn đảo ô trong mock_slots (0 = bỏ qua)")
    args = p.parse_args()
    setup_logging()
    env = load_env()
    api = env["VITE_API_BASE_URL"].rstrip("/")
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass(f"Mật khẩu {args.user}: ")
    token = login(env["VITE_COGNITO_REGION"], env["VITE_COGNITO_CLIENT_ID"], args.user, password)
    auth = {"Authorization": f"Bearer {token}"}

    def admin(method, path, body=None):
        return http(method, api + path, body, auth)

    def wait_session(plate, states, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, res = admin("GET", "/admin/sessions?limit=20")
            for s in res.get("items", []):
                if s.get("plate_text") == plate and s["state"] in states:
                    return s
            time.sleep(1)
        return None

    step("Thiết bị")
    _, devices = admin("GET", "/admin/devices")
    for d in devices:
        print(f"  {d['device_id']:<9} {d['state']:<8} last_seen={d['last_seen_at']}")
    states = {d["device_id"]: d["state"] for d in devices}
    ok(states.get("gate-01") == "ONLINE", "gate-01 online (mock_gate.py hoặc ESP thật)")
    ok(states.get("slots-01") == "ONLINE", "slots-01 online (mock_slots.py hoặc ESP thật)")

    step("Sơ đồ công khai")
    code, layout = http("GET", api + "/public/layout")
    free = [s["slot_id"] for s in layout["slots"] if s["status"] == "AVAILABLE"]
    ok(code == 200 and len(layout["slots"]) == 18, f"18 ô, {len(free)} trống")
    ok(bool(free), "còn ít nhất một ô trống")

    plate = f"99T-{random.randint(10000, 99999)}"
    pi = Device("pi-01").start()
    if not pi.connected.wait(45):  # mạng chậm: chờ thêm, không gửi sự kiện khi chưa nối được
        sys.exit("✗ pi-01 chưa kết nối được AWS IoT sau 60 giây — kiểm tra mạng, thử IOT_PORT=443")
    events = topic("vision", "pi-01", "events")

    step(f"Xe {plate} quẹt thẻ XANH ở làn vào")
    t0 = time.time()
    pi.publish(events, pi.envelope("vehicle_detected") | {
        "lane_id": "ENTRY", "card_color": "GREEN", "plate_text": plate, "plate_confidence": 0.95})
    s = wait_session(plate, ("RESERVED", "PARKED"))
    ok(s is not None, f"phiên tạo sau {time.time() - t0:.1f}s, gán ô {s and s['slot_id']}")
    slot = s["slot_id"]

    code, claims = admin("GET", "/kiosk/active-claims")
    mine = [c for c in claims if c["session_ref"] == s["session_ref"]]
    ok(code == 200 and mine, "kiosk thấy QR của phiên")
    claim_token = mine[0]["claim_url"].rsplit("/s/", 1)[1]
    code, claim = http("GET", f"{api}/public/claims/{claim_token}")
    ok(code == 200 and claim["slot_id"] == slot, f"trang khách: {' → '.join(claim['route_steps'])}")
    print(f"  QR: {mine[0]['claim_url']}")

    time.sleep(2)
    _, devices = admin("GET", "/admin/devices")
    gate = next(d for d in devices if d["device_id"] == "gate-01")
    print(f"  cần vào: {(gate.get('gates') or {}).get('ENTRY')}")

    if args.park_wait:
        step(f"Trong cửa sổ mock_slots gõ  {slot}  để báo xe đã vào ô (chờ {args.park_wait}s)")
        parked = wait_session(plate, ("PARKED",), timeout=args.park_wait)
        print(f"  {'✓ PARKED' if parked else '… bỏ qua, vẫn thử luồng ra từ RESERVED'}")

    step("Xe quẹt thẻ ĐỎ ở làn ra (dưới 15 phút → miễn phí → tự mở cần ra)")
    pi.publish(events, pi.envelope("vehicle_detected") | {
        "lane_id": "EXIT", "card_color": "RED", "plate_text": plate, "plate_confidence": 0.95})
    s = wait_session(plate, ("EXIT_OPENED", "EXIT_REQUESTED"))
    ok(s is not None, f"trạng thái {s and s['state']}, phí {s and s.get('fee_vnd')} ₫, {s and s.get('payment_status')}")
    if s["state"] == "EXIT_REQUESTED":
        print("  (cổng chưa mở — xem cảnh báo trên dashboard: gate offline?)")
        sys.exit(1)

    step("Quản trị xác nhận xe đã qua cổng")
    code, s = admin("POST", f"/admin/sessions/{s['session_id']}/confirm-passage", {})
    ok(code == 200 and s["state"] == "CLOSED", "phiên CLOSED")
    print(f"\n✅ Luồng đầu cuối chạy được. Nhớ gõ {slot} lần nữa trong mock_slots để trả ô về trống.")
    pi.stop()


if __name__ == "__main__":
    main()
