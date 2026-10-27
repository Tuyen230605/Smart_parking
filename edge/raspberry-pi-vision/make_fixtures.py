"""Tạo ảnh fixture tổng hợp (thẻ màu + biển số in) để thử pipeline khi chưa có sa bàn."""
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).parent / "fixtures"
W, H = 1280, 720


def lane(img, x0, card_bgr, plate):
    cv2.rectangle(img, (x0 + 60, 120), (x0 + 260, 320), card_bgr, -1)
    cv2.rectangle(img, (x0 + 120, 420), (x0 + 560, 540), (255, 255, 255), -1)
    cv2.rectangle(img, (x0 + 120, 420), (x0 + 560, 540), (0, 0, 0), 4)
    cv2.putText(img, plate, (x0 + 140, 505), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 6)


def main():
    OUT.mkdir(exist_ok=True)
    green, red = (60, 170, 40), (40, 40, 210)
    scenes = {
        "entry.jpg": [(0, green, "51A-12345")],
        "exit.jpg": [(640, red, "30F-67890")],
        "both.jpg": [(0, green, "51A-12345"), (640, red, "30F-67890")],
        "wrong-lane.jpg": [(0, red, "51A-12345")],
        "empty.jpg": [],
    }
    for name, lanes in scenes.items():
        img = np.full((H, W, 3), 110, np.uint8)
        cv2.line(img, (W // 2, 0), (W // 2, H), (60, 60, 60), 3)
        for args in lanes:
            lane(img, *args)
        cv2.imwrite(str(OUT / name), img)
        print(OUT / name)


if __name__ == "__main__":
    main()
