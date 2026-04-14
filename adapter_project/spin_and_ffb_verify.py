#!/usr/bin/env python3
"""Direct COM13 motor rotation + FFB readiness verification for Elmo drive."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Optional

import serial


def parse_last_int(text: str) -> Optional[int]:
    nums = re.findall(r"-?\d+", text)
    if not nums:
        return None
    return int(nums[-1])


def send(ser: serial.Serial, cmd: str, wait: float = 0.05) -> str:
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 256)
    return raw.decode("ascii", errors="replace").strip()


def get_px(ser: serial.Serial) -> Optional[int]:
    return parse_last_int(send(ser, "PX", wait=0.03))


def set_mode(ser: serial.Serial, mode: int) -> bool:
    _ = send(ser, "MO=0", wait=0.04)
    _ = send(ser, f"UM={mode}", wait=0.04)
    um = send(ser, "UM", wait=0.04)
    return str(mode) in um


def torque_pulse_test(ser: serial.Serial, tc: int, hold_s: float) -> dict:
    result = {
        "test": "torque_pulse",
        "tc": tc,
        "hold_s": hold_s,
        "px_before": None,
        "px_after": None,
        "px_delta": None,
    }

    _ = send(ser, "MO=1", wait=0.05)
    px_before = get_px(ser)
    result["px_before"] = px_before

    _ = send(ser, f"TC={tc}", wait=0.0)
    time.sleep(hold_s)
    _ = send(ser, f"TC={-tc}", wait=0.0)
    time.sleep(hold_s)
    _ = send(ser, "TC=0", wait=0.0)
    time.sleep(0.08)

    px_after = get_px(ser)
    result["px_after"] = px_after

    if px_before is not None and px_after is not None:
        result["px_delta"] = abs(px_after - px_before)

    return result


def velocity_spin_test(ser: serial.Serial, jv: int, run_s: float) -> dict:
    result = {
        "test": "velocity_spin",
        "jv": jv,
        "run_s": run_s,
        "px_before": None,
        "px_after": None,
        "px_delta": None,
        "commands": {},
    }

    _ = send(ser, "MO=1", wait=0.05)
    px_before = get_px(ser)
    result["px_before"] = px_before

    # Common Elmo velocity sequence candidates.
    result["commands"]["JV_set"] = send(ser, f"JV={jv}", wait=0.03)
    result["commands"]["BG"] = send(ser, "BG", wait=0.03)

    time.sleep(run_s)

    px_mid = get_px(ser)

    result["commands"]["ST"] = send(ser, "ST", wait=0.03)
    result["commands"]["JV_zero"] = send(ser, "JV=0", wait=0.03)
    result["commands"]["BG_zero"] = send(ser, "BG", wait=0.03)

    time.sleep(0.15)
    px_after = get_px(ser)

    result["px_after"] = px_after
    if px_before is not None and px_mid is not None:
        result["px_delta"] = abs(px_mid - px_before)

    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", default="COM13")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--torque", type=int, default=280)
    p.add_argument("--hold", type=float, default=0.35)
    p.add_argument("--jv", type=int, default=1500)
    p.add_argument("--spin-seconds", type=float, default=2.0)
    p.add_argument("--json-out", default="")
    p.add_argument("--leave-enabled", action="store_true")
    args = p.parse_args()

    report = {
        "port": args.port,
        "baud": args.baud,
        "timestamp": time.time(),
        "um_selected": None,
        "torque_result": None,
        "spin_result": None,
        "rotation_ok": False,
    }

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        time.sleep(0.12)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        # Prefer UM=2 for velocity, fallback to UM=5 then UM=4.
        mode = None
        for m in (2, 5, 4):
            if set_mode(ser, m):
                mode = m
                break

        report["um_selected"] = mode

        report["torque_result"] = torque_pulse_test(ser, args.torque, args.hold)
        report["spin_result"] = velocity_spin_test(ser, args.jv, args.spin_seconds)

        spin_delta = report["spin_result"].get("px_delta")
        torque_delta = report["torque_result"].get("px_delta")
        report["rotation_ok"] = bool((spin_delta is not None and spin_delta > 100) or (torque_delta is not None and torque_delta > 100))

        if args.leave_enabled:
            _ = send(ser, "MO=1", wait=0.03)
            _ = send(ser, "TC=0", wait=0.0)
        else:
            _ = send(ser, "TC=0", wait=0.0)
            _ = send(ser, "ST", wait=0.03)
            _ = send(ser, "MO=0", wait=0.03)

    print(json.dumps(report, indent=2))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="ascii")

    return 0 if report["rotation_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
