"""Non-hard-cut seams: micro antialiasing noise passes, any real jump fails.

Reading-window text boxes keep absolute zero difference and are re-checked here
so a loosened seam gate can never leak into the text gate.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools")]

import delivery_check as qc

WIDTH, HEIGHT = 1440, 2560
BOX = [120, 240, 320, 340]            # x, y, right, bottom
PLAN = {"reading": {"B1": [1, 2, 3]}, "seams": [[3, 4]], "frames": [1, 2, 3, 4]}
BOXES = {str(frame): [BOX] for frame in (1, 2, 3)}


def write(path, image):
    path.write_bytes(cv2.imencode(".png", image)[1].tobytes())


def run_frames(mutate=None):
    """Write four identical frames, optionally patching one of them."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for frame in (1, 2, 3, 4):
            image = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
            if mutate:
                mutate(image, frame)
            write(root/f"frame-{frame}.png", image)
        with patch.object(qc, "sample_plan", return_value=PLAN):
            return qc.original_frames(root, {}, BOXES)


class SeamToleranceTests(unittest.TestCase):
    def test_limits_are_the_documented_ones(self):
        self.assertEqual(qc.SEAM_LIMITS, {"seam_delta": 0.01, "max_pixel_delta": 2,
                                          "changed_pixel_ratio": 0.0001})

    def test_concurrent_antialiasing_noise_passes_and_is_recorded(self):
        def noise(image, frame):
            if frame == 4:
                image[900, 700] = (1, 0, 0)
                image[1500, 300] = (0, 1, 0)
        result = run_frames(noise)
        row = result["seams"][0]
        self.assertEqual(row["frames"], [3, 4])
        self.assertEqual(row["changed_pixels"], 2)
        self.assertEqual(row["max_pixel_delta"], 1)
        self.assertLessEqual(row["seam_delta"], 0.01)
        self.assertLessEqual(row["changed_pixel_ratio"], 0.0001)
        self.assertEqual(result["reading"]["B1"]["maxSampleDelta"], 0)

    def test_single_pixel_ten_levels_is_a_real_jump(self):
        def jump(image, frame):
            if frame == 4:
                image[900, 700] = (10, 10, 10)
        with self.assertRaisesRegex(ValueError, "非硬切交界 3/4"):
            run_frames(jump)

    def test_thousand_pixels_two_levels_are_a_real_jump(self):
        def bleed(image, frame):
            if frame == 4:
                for index in range(1000):
                    image[200 + index * 2, 640] = (2, 2, 2)
        with self.assertRaisesRegex(ValueError, "非硬切交界 3/4"):
            run_frames(bleed)

    def test_reading_window_text_box_stays_absolute_zero(self):
        def text(image, frame):
            if frame == 2:
                image[BOX[1] + 10, BOX[0] + 10] = (1, 0, 0)
        with self.assertRaisesRegex(ValueError, "阅读窗 B1"):
            run_frames(text)

    def test_seam_passes_rejects_tampered_records(self):
        good = {"frames": [3, 4], "seam_delta": 0.0, "max_pixel_delta": 0,
                "changed_pixels": 0, "changed_pixel_ratio": 0.0}
        self.assertTrue(qc.seam_passes(good, WIDTH * HEIGHT))
        self.assertFalse(qc.seam_passes({**good, "changed_pixels": 1000}, WIDTH * HEIGHT))
        self.assertFalse(qc.seam_passes({**good, "max_pixel_delta": 3}, WIDTH * HEIGHT))
        self.assertFalse(qc.seam_passes({"frames": [3, 4], "seam_delta": 0.0}))
        self.assertFalse(qc.seam_passes({"frames": [3, 4]}))

    def test_legacy_zero_delta_reports_still_verify(self):
        # Episodes finished before 1.2.0 stored only an exact-zero delta, which
        # already proves zero changed pixels; it must not need a re-render.
        legacy = {"frames": [3, 4], "seam_delta": 0.0}
        self.assertTrue(qc.seam_row_ok(legacy, [3, 4], WIDTH * HEIGHT))
        self.assertFalse(qc.seam_row_ok(legacy, [3, 5], WIDTH * HEIGHT))
        self.assertFalse(qc.seam_row_ok({"frames": [3, 4], "seam_delta": 0.02}, [3, 4],
                                        WIDTH * HEIGHT))
        self.assertTrue(qc.seam_row_ok({"frames": [3, 4], "seam_delta": 1e-05,
                                        "max_pixel_delta": 2, "changed_pixels": 2,
                                        "changed_pixel_ratio": 2 / (WIDTH * HEIGHT)},
                                       [3, 4], WIDTH * HEIGHT))


if __name__ == "__main__":
    unittest.main()
