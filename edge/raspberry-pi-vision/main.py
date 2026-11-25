"""Vòng lặp pi-01 (bản demo đơn giản): camera → có vật trong làn → `vehicle_detected` (không biển số).

Không cần thẻ màu hay biển in: đưa tay (hoặc xe mô hình) vào khung ENTRY = một xe vào, khung EXIT = một xe ra.
Backend đánh biển demo (11111, 22222…), chờ quản trị bấm Cho vào/Cho ra rồi gửi lại danh sách xe để hiển thị.

    python main.py                                  # chạy theo config.toml
    python main.py --source 0 --dry-run             # webcam laptop, không gửi MQTT
"""
import argparse
import logging
import signal
import threading
import time

import cv2

from camera import open_camera
from cars import LotView
from detector import crop, roi_to_pixels
from presence import LanePresence, PresenceConfig
from preview import PreviewServer
from publisher import Publisher
from settings import load_config

log = logging.getLogger("pi-vision")
# Backend chỉ nhận ENTRY+GREEN và EXIT+RED (hợp đồng MQTT v1) — giữ nguyên để không phải đổi backend.
LANE_COLOR = {"ENTRY": "GREEN", "EXIT": "RED"}
BOX_COLORS = {"TRONG": (200, 200, 200), "THAY VAT": (0, 200, 255), "DA BAO": (0, 200, 0)}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.toml")
    p.add_argument("--source", help="ghi đè camera.source (ảnh/video/webcam)")
    p.add_argument("--dry-run", action="store_true", help="không kết nối MQTT, chỉ in message")
    p.add_argument("--no-preview", action="store_true")
    p.add_argument("--max-frames", type=int, default=0, help="dừng sau N frame (dùng khi thử)")
    return p.parse_args()


def annotate(frame, lanes, detectors, lot, last_event):
    out = frame.copy()
    h, w = out.shape[:2]
    thickness = max(2, w // 500)
    scale = w / 1600
    for lane_id, lane in lanes.items():
        det = detectors[lane_id]
        p0, p1 = roi_to_pixels(lane["roi"], w, h)
        cv2.rectangle(out, p0, p1, BOX_COLORS[det.state], thickness)
        label = f"{lane_id} {det.state} {det.ratio:.0%}"
        cv2.putText(out, label, (p0[0] + 10, p0[1] + 50), cv2.FONT_HERSHEY_SIMPLEX, scale * 1.2, (255, 255, 255),
                    thickness)
    cv2.putText(out, lot.summary(), (10, h - 70), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 0), thickness)
    if last_event:
        cv2.putText(out, last_event, (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 255, 255), thickness)
    return out


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.source:
        cfg["camera"]["source"] = args.source

    lanes = cfg["lanes"]
    presence_cfg = PresenceConfig(**cfg.get("presence", {}))
    detectors = {lane_id: LanePresence(lane_id, presence_cfg) for lane_id in lanes}
    lot = LotView()
    publisher = Publisher(cfg["device"], cfg["mqtt"], dry_run=args.dry_run, on_lot=lot.update)
    camera = open_camera(cfg["camera"])
    events_lock = threading.Lock()
    last_event = ""

    def fire(lane_id):
        """Báo có xe ở làn. Gọi từ vòng camera hoặc nút trên trang preview."""
        nonlocal last_event
        with events_lock:
            publisher.vehicle_detected(lane_id, LANE_COLOR[lane_id], None, 0.0)
            msg = f"Thay xe o lan {'VAO' if lane_id == 'ENTRY' else 'RA'} - cho quan tri cho phep tren web"
            log.info(msg)
            last_event = msg
            return msg

    def cars_view(message=None):
        return {**lot.snapshot(), "message": message}

    def trigger(q):
        lane = q.get("lane", "").upper()
        if lane not in LANE_COLOR:
            return cars_view("lane phải là ENTRY hoặc EXIT")
        return cars_view(fire(lane))

    def background(_q):
        for det in detectors.values():
            det.reset_background()
        return cars_view("Đã chụp lại nền (bỏ tay ra khỏi khung trước khi bấm)")

    preview = None
    if cfg["preview"]["enabled"] and not args.no_preview:
        preview = PreviewServer(cfg["preview"]["port"], actions={
            "/cars": lambda _q: cars_view(), "/trigger": trigger, "/background": background,
        })
        log.info("Preview: http://<ip-pi>:%s", cfg["preview"]["port"])

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    frame_interval = 1 / cfg["camera"]["fps"]
    status_interval = cfg["mqtt"]["status_interval_s"]
    next_status = time.monotonic() + status_interval
    frames = 0
    try:
        while running:
            started = time.monotonic()
            frame = camera.read()
            if frame is None:
                log.warning("Không nhận được frame")
                time.sleep(0.5)
                continue

            for lane_id, lane in lanes.items():
                if detectors[lane_id].update(crop(frame, lane["roi"]), started):
                    fire(lane_id)

            if preview:
                preview.update(frame, annotate(frame, lanes, detectors, lot, last_event), cfg["preview"]["width"])
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
