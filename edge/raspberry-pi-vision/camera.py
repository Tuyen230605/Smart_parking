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
        # Cáp CSI lỗi làm camera treo ("Camera frontend has timed out"): chờ tối đa 3 s rồi trả None
        # để vòng lặp vẫn chạy (trang xem trước, MQTT, nút thử vẫn dùng được).
        try:
            return self.cam.capture_array("main", wait=3)
        except TimeoutError:
            return None

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


class NoCamera:
    """Không mở được camera (chưa cắm, cáp hỏng): dịch vụ vẫn chạy để demo bằng nút Thử xe VÀO/RA."""

    def read(self):
        return None

    def close(self):
        pass


def open_camera(cfg):
    source = str(cfg["source"])
    if source == "picamera2":
        try:
            return PiCamera(cfg["width"], cfg["height"], int(cfg.get("camera_num", 0)))
        except Exception as err:  # noqa: BLE001 — thiếu camera không được làm sập dịch vụ
            import logging
            logging.getLogger(__name__).error("Không mở được camera: %s — chạy tiếp không camera", err)
            return NoCamera()
    if Path(source).suffix.lower() in IMAGE_SUFFIXES:
        return StillImage(source)
    return CvSource(source)
