"""Mock pi-01: phát `vehicle_detected` theo kịch bản, cùng schema/topic với Pi thật.

    python mock_pi.py entry-ok                 # MQTT localhost:1883 theo config.toml
    python mock_pi.py all --dry-run            # in toàn bộ fixture JSON
    python mock_pi.py replay                   # gửi lại đúng một event_id hai lần (SIM-10)
"""
import argparse
import copy
import json
import time
import tomllib

from publisher import Publisher

SCENARIOS = {
    "entry-ok": ("ENTRY", "GREEN", "51A-12345", 0.93),
    "exit-ok": ("EXIT", "RED", "51A-12345", 0.91),
    "low-confidence": ("ENTRY", "GREEN", "51A-1Z345", 0.42),
    "no-plate": ("ENTRY", "GREEN", None, 0.0),
    "wrong-lane": ("ENTRY", "RED", "30F-67890", 0.95),
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scenario", choices=[*SCENARIOS, "replay", "all"])
    p.add_argument("--config", default="config.toml")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)

    pub = Publisher(cfg["device"], cfg["mqtt"], dry_run=args.dry_run)
    time.sleep(0 if args.dry_run else 1)  # chờ kết nối
    if args.scenario == "replay":
        event = pub.vehicle_detected(*SCENARIOS["entry-ok"])
        pub._publish(pub.events_topic, copy.deepcopy(event))
    else:
        names = SCENARIOS if args.scenario == "all" else [args.scenario]
        for name in names:
            event = pub.vehicle_detected(*SCENARIOS[name])
            if args.dry_run:
                print(f"# {name}\n{json.dumps(event, indent=2, ensure_ascii=False)}")
    time.sleep(0 if args.dry_run else 1)  # chờ QoS1 gửi xong
    pub.close()


if __name__ == "__main__":
    main()
