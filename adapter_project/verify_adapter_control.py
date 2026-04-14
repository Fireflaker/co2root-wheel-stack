#!/usr/bin/env python3
"""Direct control verification for Adapter project on Elmo COM port."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import serial


def parse_last_int(text: str):
    m = re.findall(r"-?\d+", text)
    return int(m[-1]) if m else None


def send(ser: serial.Serial, cmd: str, wait: float = 0.05) -> str:
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 128)
    return raw.decode("ascii", errors="replace").strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", default="COM13")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--tc", type=int, default=140)
    p.add_argument("--hold-ms", type=int, default=250)
    p.add_argument("--json-out", default="")
    p.add_argument("--leave-enabled", action="store_true")
    args = p.parse_args()

    result = {
        "port": args.port,
        "baud": args.baud,
        "tc": args.tc,
        "mo": None,
        "px_before": None,
        "px_after": None,
        "px_delta": None,
        "pass": False,
    }

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        time.sleep(0.12)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        mo = parse_last_int(send(ser, "MO"))
        if mo != 1:
            send(ser, "MO=1")
            time.sleep(0.08)
            mo = parse_last_int(send(ser, "MO"))
        result["mo"] = mo

        px_before = parse_last_int(send(ser, "PX"))
        result["px_before"] = px_before

        # Small bidirectional pulse for safe movement proof.
        send(ser, f"TC={args.tc}", wait=0.0)
        time.sleep(args.hold_ms / 1000.0)
        send(ser, f"TC={-args.tc}", wait=0.0)
        time.sleep(args.hold_ms / 1000.0)
        send(ser, "TC=0", wait=0.0)
        time.sleep(0.1)

        px_after = parse_last_int(send(ser, "PX"))
        result["px_after"] = px_after

        if not args.leave_enabled:
            send(ser, "TC=0", wait=0.0)
            send(ser, "ST", wait=0.03)
            send(ser, "MO=0", wait=0.03)

    if px_before is not None and px_after is not None:
        result["px_delta"] = abs(px_after - px_before)
        result["pass"] = result["px_delta"] >= 100

    print(json.dumps(result, indent=2))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="ascii")

    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
