"""python -m unittest test_presence"""
import unittest

import numpy as np

from cars import LotView
from presence import LanePresence, PresenceConfig


def scene(hand=False, brightness=120):
    img = np.full((200, 320, 3), brightness, np.uint8)
    img[::20, :] = brightness + 40  # vân nền để không phải ảnh phẳng
    if hand:
        img[60:160, 100:220] = 30  # "bàn tay" tối che giữa khung
    return img


class PresenceTest(unittest.TestCase):
    def setUp(self):
        self.det = LanePresence("ENTRY", PresenceConfig(stable_frames=3, clear_frames=4, cooldown_s=0))
        self.t = 0.0

    def feed(self, img, n=1):
        fired = 0
        for _ in range(n):
            self.t += 0.1
            fired += self.det.update(img, self.t)
        return fired

    def test_one_event_per_hand(self):
        self.assertEqual(self.feed(scene(), 5), 0)
        self.assertEqual(self.feed(scene(hand=True), 20), 1)  # giữ tay lâu vẫn chỉ một lượt
        self.assertEqual(self.feed(scene(), 5), 0)
        self.assertEqual(self.feed(scene(hand=True), 5), 1)  # rút tay ra rồi đưa lại → lượt mới

    def test_flicker_is_ignored(self):
        self.feed(scene(), 5)
        self.assertEqual(self.feed(scene(hand=True), 2), 0)  # chưa đủ stable_frames
        self.assertEqual(self.feed(scene(), 5), 0)

    def test_global_brightness_change_is_not_a_car(self):
        self.feed(scene(), 5)
        self.assertEqual(self.feed(scene(brightness=170), 10), 0)

    def test_object_left_in_lane_is_absorbed(self):
        self.det.cfg.absorb_after_s = 1.0
        self.feed(scene(), 5)
        self.assertEqual(self.feed(scene(hand=True), 30), 1)
        self.assertEqual(self.det.state, "TRONG")


class LotViewTest(unittest.TestCase):
    def test_shows_backend_list(self):
        lot = LotView()
        lot.update({"message_type": "lot_state", "in_lot": ["11111", "22222"], "pending_entry": ["33333"],
                    "pending_exit": [], "occurred_at": "t"})
        self.assertEqual(lot.snapshot()["in_lot"], ["11111", "22222"])
        self.assertEqual(lot.summary(), "Trong bai: 11111, 22222 | Cho vao: 33333")
        lot.update({"message_type": "other"})
        self.assertEqual(lot.snapshot()["pending_entry"], ["33333"])


if __name__ == "__main__":
    unittest.main()
