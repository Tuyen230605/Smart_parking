"""python -m unittest test_detector"""
import unittest

import numpy as np

from detector import CardDetector, LaneTracker, PlateReading, normalize_plate

COLORS = {
    "GREEN": {"ranges": [[[40, 80, 60], [85, 255, 255]]]},
    "RED": {"ranges": [[[0, 110, 70], [10, 255, 255]], [[170, 110, 70], [180, 255, 255]]]},
}


def tracker():
    return LaneTracker("ENTRY", stable_frames=3, clear_frames=2, ocr_attempts=2,
                       dedupe_window_s=5, confidence_threshold=0.85)


class NormalizePlateTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(normalize_plate("51A-123.45"), "51A-12345")
        self.assertEqual(normalize_plate("51a 1234"), "51A-1234")
        self.assertEqual(normalize_plate("59X1 23456"), "59X1-23456")
        self.assertEqual(normalize_plate("51A12345"), "51A-12345")
        self.assertEqual(normalize_plate("59X123456"), "59X1-23456")
        self.assertIsNone(normalize_plate("HELLO"))


class CardDetectorTest(unittest.TestCase):
    def test_colors(self):
        d = CardDetector(COLORS, 0.04)
        self.assertEqual(d.detect(np.full((50, 50, 3), (40, 170, 60), np.uint8))[0], "GREEN")
        self.assertEqual(d.detect(np.full((50, 50, 3), (40, 40, 210), np.uint8))[0], "RED")
        self.assertIsNone(d.detect(np.full((50, 50, 3), 110, np.uint8))[0])


class LaneTrackerTest(unittest.TestCase):
    def test_emits_once_per_vehicle(self):
        t = tracker()
        self.assertFalse(t.update("GREEN"))
        self.assertFalse(t.update("GREEN"))
        self.assertTrue(t.update("GREEN"))
        det = t.add_reading(PlateReading("51A-12345", 0.95), now=0)
        self.assertEqual((det.card_color, det.plate_text), ("GREEN", "51A-12345"))
        self.assertFalse(t.update("GREEN"))  # xe vẫn đứng đó: không phát lại

    def test_low_confidence_uses_best_attempt(self):
        t = tracker()
        for _ in range(3):
            t.update("GREEN")
        self.assertIsNone(t.add_reading(PlateReading(None, 0.0), now=0))
        det = t.add_reading(PlateReading("51A-1Z345", 0.4), now=0)
        self.assertEqual(det.plate_text, "51A-1Z345")

    def test_dedupe_window_after_card_leaves(self):
        t = tracker()
        for _ in range(3):
            t.update("GREEN")
        t.add_reading(PlateReading("51A-12345", 0.95), now=0)
        t.update(None)
        t.update(None)  # đủ clear_frames
        for _ in range(3):
            t.update("GREEN")
        self.assertIsNone(t.add_reading(PlateReading("51A-12345", 0.95), now=3))
        t.update(None)
        t.update(None)
        for _ in range(3):
            t.update("GREEN")
        self.assertIsNotNone(t.add_reading(PlateReading("51A-12345", 0.95), now=10))


if __name__ == "__main__":
    unittest.main()
