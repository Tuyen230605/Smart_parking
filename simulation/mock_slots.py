"""Mock ESP32 `slots-01`: 1 "cảm biến" F1-A1 + 17 "nút" — thay board thật cho tới khi nạp firmware.

    python simulation/mock_slots.py            # nối AWS IoT bằng cert slots-01
    python simulation/mock_slots.py --local    # Mosquitto local

Gõ trong cửa sổ:
  F1-B2 hoặc 4    đảo trạng thái ô (số theo bảng S0/B1…B17 ở docs/parking-layout.md)
  l               liệt kê 18 ô
  s               gửi snapshot ngay
  full / clear    tất cả có xe (SIM-06) / tất cả trống
  off 100         ngắt MQTT 100 giây rồi nối lại (SIM-11)
  q               thoát
Trạng thái lưu vào simulation/.slots-state.json giống NVS của ESP32 (SIM-05).
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

from devices import Device, setup_logging, topic

SLOT_IDS = [f"F{f}-{r}{c}" for f in (1, 2) for r in "ABC" for c in (1, 2, 3)]
STATE_FILE = Path(__file__).with_name(".slots-state.json")
log = logging.getLogger("mock")


def source(slot_id):
    return "SENSOR" if slot_id == "F1-A1" else "BUTTON"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--local", action="store_true")
    p.add_argument("--interval", type=int, default=30, help="chu kỳ snapshot/status (giây)")
    args = p.parse_args()
    setup_logging()

    state = {s: False for s in SLOT_IDS}
    if STATE_FILE.exists():
        state.update({k: v for k, v in json.loads(STATE_FILE.read_text()).items() if k in state})
    state_topic = topic("slots", "slots-01", "state")
    dev = None

    def save():
        STATE_FILE.write_text(json.dumps(state))

    def snapshot():
        dev.publish(state_topic, dev.envelope("slots_snapshot") | {
            "slots": [{"slot_id": s, "occupied": state[s], "source": source(s)} for s in SLOT_IDS]}, quiet=True)
        log.info("→ snapshot 18 ô (%d có xe)", sum(state.values()))

    def changed(slot_id):
        dev.publish(state_topic, dev.envelope("slot_changed") | {
            "slot_id": slot_id, "occupied": state[slot_id], "source": source(slot_id)})

    def show():
        for f in (1, 2):
            print(f"  Tầng {f}: " + "  ".join(
                f"{i:>2}:{s}{'■' if state[s] else '□'}" for i, s in enumerate(SLOT_IDS) if s.startswith(f"F{f}")))

    dev = Device("slots-01", local=args.local, on_connect=snapshot).start()
    dev.every(args.interval, lambda: (snapshot(), dev.status()))
    show()
    print("Gõ mã ô (F1-B2) hoặc số 0–17 để đảo trạng thái; 'l' liệt kê; 'q' thoát.")

    for line in sys.stdin:
        cmd = line.strip().upper()
        if not cmd:
            continue
        if cmd == "Q":
            break
        if cmd == "L":
            show()
        elif cmd == "S":
            snapshot()
        elif cmd in ("FULL", "CLEAR"):
            for s in SLOT_IDS:
                state[s] = cmd == "FULL"
            save()
            snapshot()
        elif cmd.startswith("OFF"):
            secs = int(cmd.split()[1]) if len(cmd.split()) > 1 else 100
            log.info("Ngắt MQTT %d giây…", secs)
            dev.client.disconnect()
            time.sleep(secs)
            dev.client.reconnect()
        else:
            slot_id = SLOT_IDS[int(cmd)] if cmd.isdigit() and int(cmd) < 18 else cmd
            if slot_id not in state:
                print("  Không có ô này")
                continue
            state[slot_id] = not state[slot_id]
            save()
            changed(slot_id)
            print(f"  {slot_id}: {'CÓ XE' if state[slot_id] else 'trống'} ({source(slot_id).lower()})")
    dev.stop()


if __name__ == "__main__":
    main()
