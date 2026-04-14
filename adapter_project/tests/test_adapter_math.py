import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vjoy_state import pedal_to_vjoy_axis, released_pedal_vjoy_axis

from adapter_main import (
    DEFAULT_CONFIG,
    current_a_to_il_counts,
    ffb_to_il,
    ffb_to_pr,
    ffb_to_tc,
    parse_last_int,
    px_to_vjoy_axis,
    response_indicates_elmo_error,
    resolve_max_position_counts,
    resolve_runtime_command_mode,
    slew_limit,
    resolve_max_current_a,
    scale_ffb_signal,
    vjoy_condition_to_ffb_raw,
    vjoy_constant_magnitude_to_ffb_raw,
    vjoy_periodic_to_ffb_raw,
    vjoy_ramp_to_ffb_raw,
    vjoy_scale_with_gains,
)


class FakeElmo:
    def __init__(self, tc_responses, ec=0):
        self.tc_responses = list(tc_responses)
        self.ec = ec
        self.um_written = []
        self.rm_written = []

    def set_tc(self, tc: int) -> str:
        if self.tc_responses:
            return self.tc_responses.pop(0)
        return ""

    def get_ec(self):
        return self.ec

    def set_um(self, um: int) -> str:
        self.um_written.append(um)
        return ""

    def set_rm(self, rm: int) -> str:
        self.rm_written.append(rm)
        return ""


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

    def test_scale_ffb_signal_applies_strength(self):
        self.assertEqual(scale_ffb_signal(10000, 1.0, 10000), 10000)
        self.assertEqual(scale_ffb_signal(10000, 0.5, 10000), 5000)
        self.assertEqual(scale_ffb_signal(-10000, 0.25, 10000), -2500)
        self.assertEqual(scale_ffb_signal(10000, 2.0, 10000), 10000)

    def test_current_a_to_il_counts(self):
        self.assertEqual(current_a_to_il_counts(2.0, 1000.0), 2000)
        self.assertEqual(current_a_to_il_counts(0.05, 1000.0), 50)

    def test_resolve_max_current_a_prefers_explicit_value(self):
        cfg = dict(DEFAULT_CONFIG)
        cfg["max_current_a"] = 0.8
        cfg["motor_rated_current_a"] = 1.3
        cfg["motor_current_utilization"] = 0.5
        self.assertEqual(resolve_max_current_a(cfg), 0.8)

    def test_resolve_max_current_a_derives_from_motor_profile(self):
        cfg = dict(DEFAULT_CONFIG)
        cfg["max_current_a"] = 0.0
        cfg["motor_rated_current_a"] = 1.3
        cfg["motor_current_utilization"] = 0.5
        self.assertAlmostEqual(resolve_max_current_a(cfg), 0.65)

    def test_ffb_to_il_uses_amp_mapping(self):
        self.assertEqual(ffb_to_il(10000, 2.0, 0.05, 10000, 1000.0), 2000)
        self.assertEqual(ffb_to_il(-10000, 2.0, 0.05, 10000, 1000.0), -2000)
        self.assertEqual(ffb_to_il(100, 2.0, 0.05, 10000, 1000.0), 50)
        self.assertEqual(ffb_to_il(-100, 2.0, 0.05, 10000, 1000.0), -50)
        self.assertEqual(ffb_to_il(0, 2.0, 0.05, 10000, 1000.0), 0)

    def test_vjoy_constant_magnitude_to_ffb_raw_applies_gain(self):
        self.assertEqual(vjoy_constant_magnitude_to_ffb_raw(10000, 255), 10000)
        self.assertEqual(vjoy_constant_magnitude_to_ffb_raw(10000, 128), 5020)
        self.assertEqual(vjoy_constant_magnitude_to_ffb_raw(-10000, 64), -2510)
        self.assertEqual(vjoy_constant_magnitude_to_ffb_raw(10000, 0), 0)

    def test_vjoy_scale_with_gains_applies_effect_and_device_gain(self):
        self.assertEqual(vjoy_scale_with_gains(10000, 255, 255), 10000)
        self.assertEqual(vjoy_scale_with_gains(10000, 128, 255), 5020)
        self.assertEqual(vjoy_scale_with_gains(10000, 128, 128), 2520)

    def test_vjoy_periodic_to_ffb_raw_uses_waveform_and_offset(self):
        self.assertEqual(vjoy_periodic_to_ffb_raw(4000, 1000, 0, 0.0, 1000, 4), 1000)
        self.assertEqual(vjoy_periodic_to_ffb_raw(4000, 0, 0, 0.25, 1000, 4), 4000)
        self.assertEqual(vjoy_periodic_to_ffb_raw(4000, 0, 0, 0.75, 1000, 4), -4000)

    def test_vjoy_ramp_to_ffb_raw_interpolates_over_duration(self):
        self.assertEqual(vjoy_ramp_to_ffb_raw(-10000, 10000, 0.0, 1000), -10000)
        self.assertEqual(vjoy_ramp_to_ffb_raw(-10000, 10000, 0.5, 1000), 0)
        self.assertEqual(vjoy_ramp_to_ffb_raw(-10000, 10000, 1.0, 1000), 10000)

    def test_vjoy_condition_to_ffb_raw_handles_spring(self):
        self.assertEqual(vjoy_condition_to_ffb_raw(8, 0, 10000, 10000, 10000, 10000, 0, 0.5, 0.0), -5000)
        self.assertEqual(vjoy_condition_to_ffb_raw(8, 0, 10000, 10000, 10000, 10000, 0, -0.5, 0.0), 5000)

    def test_vjoy_condition_to_ffb_raw_handles_damper_and_deadband(self):
        self.assertEqual(vjoy_condition_to_ffb_raw(9, 0, 10000, 10000, 10000, 10000, 0, 0.0, 0.4), -4000)
        self.assertEqual(vjoy_condition_to_ffb_raw(9, 0, 10000, 10000, 10000, 10000, 5000, 0.0, 0.4), 0)

    def test_slew_limit(self):
        self.assertEqual(slew_limit(0, 100, 12), 12)
        self.assertEqual(slew_limit(50, -100, 10), 40)
        self.assertEqual(slew_limit(10, 15, 10), 15)

    def test_px_to_vjoy_axis_bounds(self):
        max_counts = 1000
        self.assertEqual(px_to_vjoy_axis(-1000, max_counts), 1)
        self.assertEqual(px_to_vjoy_axis(1000, max_counts), 32767)

    def test_px_to_vjoy_axis_uses_center_offset(self):
        max_counts = 1000
        self.assertEqual(px_to_vjoy_axis(500, max_counts, 500), 16384)
        self.assertEqual(px_to_vjoy_axis(1500, max_counts, 500), 32767)
        self.assertEqual(px_to_vjoy_axis(-500, max_counts, 500), 1)

    def test_pedal_to_vjoy_axis_is_inverted_for_lfs(self):
        self.assertEqual(pedal_to_vjoy_axis(0.0), 32767)
        self.assertEqual(pedal_to_vjoy_axis(1.0), 0)

    def test_released_pedal_axis_matches_zero_percent(self):
        self.assertEqual(released_pedal_vjoy_axis(), 32767)

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

    def test_response_indicates_elmo_error(self):
        self.assertTrue(response_indicates_elmo_error("\r\x15?;"))
        self.assertFalse(response_indicates_elmo_error("MO=1;"))

    def test_resolve_runtime_command_mode_keeps_tc_when_probe_passes(self):
        elmo = FakeElmo(["", ""], ec=0)
        cfg = dict(DEFAULT_CONFIG)
        cfg["tc_probe_value"] = 10
        mode, detail = resolve_runtime_command_mode(elmo, cfg, "tc")
        self.assertEqual(mode, "tc")
        self.assertIn("accepted", detail)
        self.assertEqual(elmo.um_written, [])

    def test_resolve_runtime_command_mode_falls_back_to_pr(self):
        elmo = FakeElmo(["\r\x15?;"], ec=21)
        cfg = dict(DEFAULT_CONFIG)
        mode, detail = resolve_runtime_command_mode(elmo, cfg, "tc")
        self.assertEqual(mode, "pr")
        self.assertIn("falling back to PR", detail)
        self.assertEqual(elmo.um_written, [int(cfg["pr_fallback_um"])])
        self.assertEqual(elmo.rm_written, [int(cfg["pr_fallback_rm"])])

    def test_resolve_runtime_command_mode_requires_true_torque(self):
        elmo = FakeElmo(["\r\x15?;"], ec=21)
        cfg = dict(DEFAULT_CONFIG)
        cfg["require_true_torque"] = True
        with self.assertRaisesRegex(RuntimeError, "True torque required"):
            resolve_runtime_command_mode(elmo, cfg, "tc")

    def test_resolve_runtime_command_mode_keeps_il(self):
        elmo = FakeElmo([], ec=0)
        mode, detail = resolve_runtime_command_mode(elmo, dict(DEFAULT_CONFIG), "il")
        self.assertEqual(mode, "il")
        self.assertIn("runtime mode=il", detail)


if __name__ == "__main__":
    unittest.main()
