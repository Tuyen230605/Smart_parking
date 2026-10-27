"""Nguồn frame BGR: Camera Module 3 qua Picamera2, webcam, video hoặc ảnh tĩnh."""
import time
from pathlib import Path

import cv2

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


class PiCamera:
    def __init__(self, width, height):
        from libcamera import controls
        from picamera2 import Picamera2

        self.cam = Picamera2()
        # "RGB888" của Picamera2 trả mảng theo thứ tự BGR, dùng thẳng với OpenCV.
        config = self.cam.create_video_configuration(main={"size": (width, height), "format": "RGB888"})
        self.cam.configure(config)
        self.cam.start()
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
        return PiCamera(cfg["width"], cfg["height"])
    if Path(source).suffix.lower() in IMAGE_SUFFIXES:
        return StillImage(source)
    return CvSource(source)
