#!/usr/bin/env python3
"""Mock slots-01 (MQTT v1.1).
Lệnh: toggle <ô> | set <ô> 0/1 | fault on/off | mute on/off | reboot | drop | up | snap | run <file.json> | quit
  fault  = ToF lỗi (F1-A1 báo occupied=true, device_status DEGRADED)
  mute   = ngừng gửi hết (giả lập thiết bị chết; sau 90 s backend đặt 18 ô UNKNOWN)
  reboot = boot_id mới, seq về 0 | drop/up = ngắt/nối socket đột ngột (broker phát Last Will)
Chú ý: client ID mặc định là slots-01, không chạy song song với thiết bị thật trên AWS.
Biến môi trường: MQTT_HOST (localhost), MQTT_PORT, TLS=1 + CA/CERT/KEY, PERIOD (30), CLIENT_ID."""
import json, os, sys, threading, time, uuid
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

SITE, DEV = "site-01", "slots-01"
IDS = [f"F{f}-{r}{c}" for f in (1, 2) for r in "ABC" for c in (1, 2, 3)]
T_STATE = f"parking/v1/{SITE}/slots/{DEV}/state"
T_STATUS = f"parking/v1/{SITE}/devices/{DEV}/status"
PERIOD = int(os.getenv("PERIOD", "30"))
FAULT_OCCUPIED = True                     # khớp TOF_FAULT_OCCUPIED trong config.h

occ = {i: 0 for i in IDS}
tof_fault, muted = False, False
boot_id, seq, lock = str(uuid.uuid4()), 0, threading.RLock()

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=os.getenv("CLIENT_ID", DEV))
if os.getenv("TLS"):
    c.tls_set(os.environ["CA"], os.environ["CERT"], os.environ["KEY"])

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def header(kind):
    global seq
    h = {"schema_version": 1, "message_type": kind, "event_id": str(uuid.uuid4()),
         "device_id": DEV, "boot_id": boot_id, "seq": seq, "occurred_at": now_iso()}
    seq += 1
    return h

def reported(i):
    return bool(FAULT_OCCUPIED) if (i == "F1-A1" and tof_fault) else bool(occ[i])

def source(i):
    return "SENSOR" if i == "F1-A1" else "BUTTON"

def slot_changed(i):
    if muted: return
    with lock:
        m = {**header("slot_changed"), "slot_id": i, "occupied": reported(i), "source": source(i)}
        c.publish(T_STATE, json.dumps(m), qos=1, retain=False)
    print("slot_changed", i, m["occupied"])

def snapshot(tag="periodic"):
    if muted: return
    with lock:
        m = {**header("slots_snapshot"),
             "slots": [{"slot_id": i, "occupied": reported(i), "source": source(i)} for i in IDS]}
        c.publish(T_STATE, json.dumps(m), qos=1, retain=False)
    print("snapshot", tag, "".join("1" if s["occupied"] else "0" for s in m["slots"]))

def status():
    if muted: return
    with lock:
        m = {**header("device_status"), "state": "DEGRADED" if tof_fault else "ONLINE",
             "firmware_version": "mock"}
        c.publish(T_STATUS, json.dumps(m), qos=1, retain=False)

def set_will():
    will = {"schema_version": 1, "message_type": "device_status", "event_id": str(uuid.uuid4()),
            "device_id": DEV, "boot_id": boot_id, "seq": 0, "occurred_at": now_iso(),
            "state": "OFFLINE", "firmware_version": "mock"}
    c.will_set(T_STATUS, json.dumps(will), qos=1, retain=False)

def on_connect(cl, ud, flags, rc, props):          # reconnect giữ nguyên boot_id và seq
    status(); snapshot("reconnect")

def connect():
    set_will()
    c.connect(os.getenv("MQTT_HOST", "localhost"),
              int(os.getenv("MQTT_PORT", "8883" if os.getenv("TLS") else "1883")), 30)

def step(st):
    global tof_fault, muted, boot_id, seq
    d = st["do"]
    if d == "slot":
        occ[st["slot"]] = int(st["occupied"]); slot_changed(st["slot"])
    elif d == "tof_fault":
        tof_fault = bool(st["value"]); slot_changed("F1-A1"); status()
    elif d == "mute":
        muted = bool(st["value"])
        print("muted" if muted else "unmuted")
        if not muted: status(); snapshot("unmute")
    elif d == "reboot":
        with lock:
            boot_id, seq = str(uuid.uuid4()), 0
        status(); snapshot("boot")
    elif d == "snapshot":
        snapshot()
    elif d == "drop":
        c.loop_stop()
        try: c._sock.close()                       # ngắt không DISCONNECT sạch => broker phát Last Will
        except Exception: pass
        print("dropped")
    elif d == "up":
        c.reconnect(); c.loop_start(); print("reconnected")

def run(path):
    sc = json.load(open(path, encoding="utf-8")); t0 = time.time(); print("==", sc["name"])
    for st in sc["steps"]:
        time.sleep(max(0, t0 + st["at"] - time.time())); step(st)

def periodic():
    while True:
        time.sleep(PERIOD)
        if c.is_connected(): snapshot(); status()

def cli(line):
    p = line.split()
    if not p: return True
    if p[0] == "quit": return False
    if p[0] in ("toggle", "set") and len(p) > 1 and p[1] in IDS:
        occ[p[1]] = occ[p[1]] ^ 1 if p[0] == "toggle" else int(p[2]); slot_changed(p[1])
    elif p[0] in ("fault", "mute") and len(p) > 1:
        step({"do": "tof_fault" if p[0] == "fault" else "mute", "value": p[1] == "on"})
    elif p[0] in ("reboot", "drop", "up"):
        step({"do": p[0]})
    elif p[0] == "snap":
        snapshot()
    elif p[0] == "run" and len(p) > 1:
        run(p[1])
    else:
        print(__doc__)
    return True

if __name__ == "__main__":
    c.on_connect = on_connect
    connect(); c.loop_start()
    threading.Thread(target=periodic, daemon=True).start()
    if len(sys.argv) > 1:
        run(sys.argv[1]); time.sleep(2)
    else:
        for line in sys.stdin:
            if not cli(line.strip()): break
    c.loop_stop()