"""Mock ESP32 `gate-01`: 2 cần chắn + OLED — thay board thật cho tới khi nạp firmware.

    python simulation/mock_gate.py                 # nối AWS IoT bằng cert gate-01
    python simulation/mock_gate.py --hold 5        # cần mở 5 giây rồi tự đóng
    python simulation/mock_gate.py --fail-motor    # mọi lệnh trả ERROR MOTOR_TIMEOUT
    python simulation/mock_gate.py --no-ack        # nuốt lệnh, không ACK (thử cảnh báo GATE_NO_ACK)

Xử lý giống firmware: bỏ lệnh sai schema/target, quá expires_at, trùng command_id (nhớ 20 ID gần nhất).
"""
import argparse
import collections
import logging
import queue
import threading
import time
from datetime import datetime, timezone

from devices import Device, parse_iso, setup_logging, topic, utc_now

log = logging.getLogger("mock")
SCREEN_PRIORITY = {"ERROR": 3, "LOT_FULL": 3, "EXIT_FEE": 2, "ENTRY_ROUTE": 1, "IDLE": 0}
DISPLAY_HOLD_S = 3


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--local", action="store_true")
    p.add_argument("--hold", type=float, default=5, help="số giây giữ cần mở trước khi tự đóng")
    p.add_argument("--fail-motor", action="store_true")
    p.add_argument("--no-ack", action="store_true")
    args = p.parse_args()
    setup_logging()

    gate_cmd_t = topic("gates", "gate-01", "commands")
    disp_cmd_t = topic("displays", "gate-01", "commands")
    gate_tel_t = topic("gates", "gate-01", "telemetry")
    disp_tel_t = topic("displays", "gate-01", "telemetry")
    seen = collections.deque(maxlen=20)
    gate_state = {"ENTRY": "CLOSED", "EXIT": "CLOSED"}
    close_at = {"ENTRY": None, "EXIT": None}
    gate_work, disp_work = queue.Queue(), queue.Queue()  # hai hàng riêng: OLED chờ không làm trễ servo
    display = {"screen": "IDLE", "at": 0.0}
    dev = None

    def telemetry(gate, state, command_id, error_code=None):
        if gate:
            gate_state[gate] = state
        dev.publish(gate_tel_t, dev.envelope("gate_telemetry") | {
            "command_id": command_id, "gate": gate, "state": state, "error_code": error_code})

    def reject(cmd, code):
        log.warning("✗ bỏ lệnh %s: %s", cmd.get("command_id"), code)
        telemetry(cmd.get("gate") if cmd.get("gate") in gate_state else None, "ERROR", cmd.get("command_id"), code)

    def validate(cmd, expected_type):
        if cmd.get("schema_version") != 1 or cmd.get("message_type") != expected_type:
            return "SCHEMA_UNSUPPORTED"
        if cmd.get("target_device_id") != "gate-01":
            return "WRONG_TARGET"
        if cmd.get("command_id") in seen:
            return "DUPLICATE_COMMAND"
        try:
            if datetime.now(timezone.utc) > parse_iso(cmd["expires_at"]):
                return "COMMAND_EXPIRED"
        except (KeyError, ValueError):
            return "SCHEMA_UNSUPPORTED"
        return None

    def on_message(t, cmd):
        if args.no_ack:
            log.warning("(--no-ack) nuốt lệnh %s", cmd.get("command_id"))
            return
        (gate_work if t == gate_cmd_t else disp_work).put(cmd)

    def worker(q, fn):
        while True:
            fn(q.get())

    def handle_gate(cmd):
        err = validate(cmd, "gate_command")
        if not err and (cmd.get("gate") not in gate_state or cmd.get("action") not in ("OPEN", "CLOSE")):
            err = "SCHEMA_UNSUPPORTED"
        if err:
            return reject(cmd, err)
        seen.append(cmd["command_id"])
        gate, action, cid = cmd["gate"], cmd["action"], cmd["command_id"]
        if args.fail_motor:
            return telemetry(gate, "ERROR", cid, "MOTOR_TIMEOUT")
        if action == "OPEN":
            telemetry(gate, "OPENING", cid)
            time.sleep(0.6)
            telemetry(gate, "OPEN", cid)
            log.info("🚧 CẦN %s MỞ (tự đóng sau %.0fs)", gate, args.hold)
            close_at[gate] = (time.monotonic() + args.hold, cid)
        else:
            close(gate, cid)

    def close(gate, cid):
        telemetry(gate, "CLOSING", cid)
        time.sleep(0.6)
        telemetry(gate, "CLOSED", cid)
        close_at[gate] = None
        log.info("🚧 CẦN %s ĐÓNG", gate)

    def auto_close():
        while True:
            time.sleep(0.2)
            for gate, pending in list(close_at.items()):
                if pending and time.monotonic() >= pending[0]:
                    close_at[gate] = None
                    threading.Thread(target=close, args=(gate, pending[1]), daemon=True).start()

    def handle_display(cmd):
        err = validate(cmd, "display_command")
        if err:
            log.warning("✗ bỏ display %s: %s", cmd.get("command_id"), err)
            dev.publish(disp_tel_t, dev.envelope("display_telemetry") | {
                "command_id": cmd.get("command_id"), "state": "ERROR", "error_code": err})
            return
        seen.append(cmd["command_id"])
        screen = cmd.get("screen", "IDLE")
        # Ưu tiên ERROR > EXIT_FEE > ENTRY_ROUTE: màn quan trọng hơn được giữ ít nhất 3 giây.
        held = time.monotonic() - display["at"] < DISPLAY_HOLD_S
        if held and SCREEN_PRIORITY.get(screen, 0) < SCREEN_PRIORITY.get(display["screen"], 0):
            time.sleep(DISPLAY_HOLD_S - (time.monotonic() - display["at"]))
        display.update(screen=screen, at=time.monotonic())
        lines = (cmd.get("lines") or [])[:3]
        print("  ┌" + "─" * 22 + "┐\n" + "".join(f"  │ {line[:20]:<20} │\n" for line in lines + [""] * (3 - len(lines)))
              + "  └" + "─" * 22 + f"┘  OLED [{screen}]")
        dev.publish(disp_tel_t, dev.envelope("display_telemetry") | {
            "command_id": cmd["command_id"], "state": "SHOWN", "screen": screen}, quiet=True)

    dev = Device("gate-01", local=args.local, subscriptions=[gate_cmd_t, disp_cmd_t], on_message=on_message)
    threading.Thread(target=worker, args=(gate_work, handle_gate), daemon=True).start()
    threading.Thread(target=worker, args=(disp_work, handle_display), daemon=True).start()
    threading.Thread(target=auto_close, daemon=True).start()
    dev.start()
    dev.every(30, dev.status)
    log.info("Đang chờ lệnh cổng/OLED… (Ctrl+C để thoát)  %s", utc_now())
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        dev.stop()


if __name__ == "__main__":
    main()
