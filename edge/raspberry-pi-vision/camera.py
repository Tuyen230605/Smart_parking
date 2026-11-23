"""Nguồn frame BGR: camera CSI qua Picamera2 (Camera Module 3 hoặc v1.3/OV5647), webcam, video hoặc ảnh tĩnh."""
import time
from pathlib import Path

import cv2

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


class PiCamera:
    def __init__(self, width, height, camera_num=0):
        from libcamera import controls
        from picamera2 import Picamera2

        cameras = Picamera2.global_camera_info()
        if camera_num >= len(cameras):
            raise RuntimeError(f"Không có camera CSI số {camera_num} (thấy {len(cameras)}: {cameras})")
        # Pi 5 có 2 cổng CSI: camera_num chọn cổng, để dự án khác giữ camera còn lại.
        self.cam = Picamera2(camera_num)
        # "RGB888" của Picamera2 trả mảng theo thứ tự BGR, dùng thẳng với OpenCV.
        config = self.cam.create_video_configuration(main={"size": (width, height), "format": "RGB888"})
        self.cam.configure(config)
        self.cam.start()
        # Chỉ Camera Module 3 có lấy nét tự động; OV5647 (v1.3) không có AfMode, đặt vào sẽ lỗi.
        if "AfMode" in self.cam.camera_controls:
            self.cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        time.sleep(1)

    def read(self):
        return self.cam.capture_array("main")

    def close(self):
        self.cam.stop()


class CvSource:
    """Webcam hoặc video; video phát lặp lại để tiện thử."""

    def __init__(self, source):
        self.source = int(source) if str(source).isdigit() else source
        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Không mở được nguồn camera: {source}")

    def read(self):
        ok, frame = self.cap.read()
        if not ok and not isinstance(self.source, int):
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        return frame if ok else None

    def close(self):
        self.cap.release()


class StillImage:
    """Trả cùng một ảnh mỗi lần đọc để chạy thử bộ ổn định nhiều frame."""

    def __init__(self, path):
        self.frame = cv2.imread(str(path))
        if self.frame is None:
            raise RuntimeError(f"Không đọc được ảnh: {path}")

    def read(self):
        return self.frame.copy()

    def close(self):
        pass


def open_camera(cfg):
    source = str(cfg["source"])
    if source == "picamera2":
        return PiCamera(cfg["width"], cfg["height"], int(cfg.get("camera_num", 0)))
    if Path(source).suffix.lower() in IMAGE_SUFFIXES:
        return StillImage(source)
    return CvSource(source)
