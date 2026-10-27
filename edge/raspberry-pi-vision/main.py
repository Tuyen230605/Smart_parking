"""Vòng lặp pi-01: camera → màu thẻ theo làn → OCR biển số → `vehicle_detected`.

    python main.py                                  # chạy theo config.toml
    python main.py --source fixtures/entry.jpg --dry-run
"""
import argparse
import logging
import signal
import time
import tomllib

import cv2

from camera import open_camera
from detector import CardDetector, LaneTracker, PlateReader, crop, roi_to_pixels
from preview import PreviewServer
from publisher import Publisher

log = logging.getLogger("pi-vision")
BOX_COLORS = {"GREEN": (0, 200, 0), "RED": (0, 0, 230), None: (200, 200, 200)}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.toml")
    p.add_argument("--source", help="ghi đè camera.source (ảnh/video/webcam)")
    p.add_argument("--dry-run", action="store_true", help="không kết nối MQTT, chỉ in message")
    p.add_argument("--no-preview", action="store_true")
    p.add_argument("--max-frames", type=int, default=0, help="dừng sau N frame (dùng khi thử)")
    return p.parse_args()


def annotate(frame, lanes, states, last_event):
    out = frame.copy()
    h, w = out.shape[:2]
    thickness = max(2, w // 500)
    for lane_id, lane in lanes.items():
        color, ratios, tracker = states[lane_id]
        p0, p1 = roi_to_pixels(lane["roi"], w, h)
        cv2.rectangle(out, p0, p1, BOX_COLORS[color], thickness)
        if lane.get("plate_roi"):
            q0, q1 = roi_to_pixels(lane["plate_roi"], w, h)
            cv2.rectangle(out, q0, q1, (255, 200, 0), thickness)
        ratio_text = " ".join(f"{k[0]}={v:.2f}" for k, v in ratios.items())
        label = f"{lane_id} {tracker.state} {ratio_text}"
        cv2.putText(out, label, (p0[0] + 10, p0[1] + 40), cv2.FONT_HERSHEY_SIMPLEX, w / 1600, (255, 255, 255), thickness)
    if last_event:
        cv2.putText(out, last_event, (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, w / 1600, (0, 255, 255), thickness)
    return out


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    if args.source:
        cfg["camera"]["source"] = args.source

    det = cfg["detection"]
    lanes = cfg["lanes"]
    camera = open_camera(cfg["camera"])
    cards = CardDetector(cfg["colors"], det["min_card_ratio"])
    reader = PlateReader()
    publisher = Publisher(cfg["device"], cfg["mqtt"], dry_run=args.dry_run)
    preview = None
    if cfg["preview"]["enabled"] and not args.no_preview:
        preview = PreviewServer(cfg["preview"]["port"])
        log.info("Preview: http://<ip-pi>:%s", cfg["preview"]["port"])
    trackers = {
        lane_id: LaneTracker(
            lane_id, det["stable_frames"], det["clear_frames"], det["ocr_attempts"],
            det["dedupe_window_s"], det["plate_confidence_threshold"],
        )
        for lane_id in lanes
    }

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    frame_interval = 1 / cfg["camera"]["fps"]
    status_interval = cfg["mqtt"]["status_interval_s"]
    next_status = time.monotonic() + status_interval
    last_event = ""
    frames = 0
    try:
        while running:
            started = time.monotonic()
            frame = camera.read()
            if frame is None:
                log.warning("Không nhận được frame")
                time.sleep(0.5)
                continue

            states = {}
            for lane_id, lane in lanes.items():
                color, ratios = cards.detect(crop(frame, lane["roi"]))
                tracker = trackers[lane_id]
                if tracker.update(color):
                    plate_img = crop(frame, lane.get("plate_roi") or lane["roi"])
                    detection = tracker.add_reading(reader.read(plate_img), started)
                    if detection:
                        publisher.vehicle_detected(
                            detection.lane_id, detection.card_color,
                            detection.plate_text, detection.plate_confidence,
                        )
                        last_event = f"{detection.lane_id} {detection.card_color} {detection.plate_text} {detection.plate_confidence}"
                states[lane_id] = (color, ratios, tracker)

            if preview:
                preview.update(frame, annotate(frame, lanes, states, last_event), cfg["preview"]["width"])
            if started >= next_status:
                publisher.status()
                next_status = started + status_interval

            frames += 1
            if args.max_frames and frames >= args.max_frames:
                break
            time.sleep(max(0.0, frame_interval - (time.monotonic() - started)))
    finally:
        camera.close()
        publisher.close()


if __name__ == "__main__":
    main()
