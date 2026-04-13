import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapter_main import (
    DEFAULT_CONFIG,
    ffb_to_pr,
    ffb_to_tc,
    parse_last_int,
    px_to_vjoy_axis,
    resolve_max_position_counts,
    slew_limit,
)


class AdapterMathTests(unittest.TestCase):
    def test_parse_last_int(self):
        self.assertEqual(parse_last_int("MO=1\r\nOK\r\n"), 1)
        self.assertEqual(parse_last_int("PX=12345\r"), 12345)
        self.assertIsNone(parse_last_int("NO_NUMBERS"))

    def test_ffb_to_tc_clamps(self):
        self.assertEqual(ffb_to_tc(10000, 300, 10000), 300)
        self.assertEqual(ffb_to_tc(-10000, 300, 10000), -300)
        self.assertEqual(ffb_to_tc(0, 300, 10000), 0)

    def test_ffb_to_pr_clamps(self):
        self.assertEqual(ffb_to_pr(10000, 220, 10000), 220)
        self.assertEqual(ffb_to_pr(-10000, 220, 10000), -220)
        self.assertEqual(ffb_to_pr(0, 220, 10000), 0)

    def test_slew_limit(self):
        self.assertEqual(slew_limit(0, 100, 12), 12)
        self.assertEqual(slew_limit(50, -100, 10), 40)
        self.assertEqual(slew_limit(10, 15, 10), 15)

    def test_px_to_vjoy_axis_bounds(self):
        max_counts = 1000
        self.assertEqual(px_to_vjoy_axis(-1000, max_counts), 1)
        self.assertEqual(px_to_vjoy_axis(1000, max_counts), 32767)

    def test_resolve_max_position_counts(self):
        cfg = dict(DEFAULT_CONFIG)
        cfg["max_position_counts"] = 0
        cfg["encoder_bits"] = 17
        cfg["wheel_lock_deg"] = 540.0
        val = resolve_max_position_counts(cfg)
        self.assertGreater(val, 0)

        cfg2 = dict(cfg)
        cfg2["max_position_counts"] = 4321
        self.assertEqual(resolve_max_position_counts(cfg2), 4321)


if __name__ == "__main__":
    unittest.main()
