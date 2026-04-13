import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wheel_sim_bridge import (  # noqa: E402
    angle_to_centered_steering,
    angle_to_steering_axis,
    counts_to_16bit,
    extract_px,
    parse_all_ints,
)


class WheelBridgeMathTests(unittest.TestCase):
    def test_parse_helpers(self):
        self.assertEqual(parse_all_ints("PX=12 -34 56"), [12, -34, 56])
        self.assertEqual(extract_px("PX=12345\r\nOK"), 12345)
        self.assertIsNone(extract_px("NO DATA"))

    def test_counts_to_16bit(self):
        self.assertEqual(counts_to_16bit(None), 0)
        self.assertEqual(counts_to_16bit(0), 0)
        self.assertEqual(counts_to_16bit(0x007FFFFF), 0xFFFF)

    def test_angle_to_steering_axis_bounds(self):
        self.assertAlmostEqual(angle_to_steering_axis(0), -1.0, places=4)
        self.assertAlmostEqual(angle_to_steering_axis(65535), 1.0, places=4)
        self.assertAlmostEqual(angle_to_steering_axis(32768), 0.0, places=3)

    def test_angle_to_centered_wraparound(self):
        center = 65000
        near_center = angle_to_centered_steering(65000, center)
        wrapped_right = angle_to_centered_steering(100, center)

        self.assertAlmostEqual(near_center, 0.0, places=4)
        self.assertTrue(-1.0 <= wrapped_right <= 1.0)


if __name__ == "__main__":
    unittest.main()
