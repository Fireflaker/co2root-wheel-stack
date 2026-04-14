#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path

import serial


def txrx(ser: serial.Serial, cmd: str, wait: float = 0.05) -> dict:
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 256)
    txt = raw.decode("ascii", errors="replace").strip()
    return {"cmd": cmd, "raw_hex": raw.hex(), "text": txt}


def main() -> int:
    seq = [
        ("MO=0", 0.04),
        ("UM=1", 0.04),
        ("MO=1", 0.04),
        ("UM", 0.04),
        ("MO", 0.04),
        ("RF", 0.04),
        ("RM", 0.04),
        ("PM", 0.04),
        ("TC=200", 0.07),
        ("EC", 0.05),
        ("SR", 0.05),
        ("TC=0", 0.03),
        ("EC", 0.05),
        ("SR", 0.05),
    ]

    out = []
    with serial.Serial("COM13", 115200, timeout=0.2) as ser:
        time.sleep(0.12)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        for cmd, wait in seq:
            row = txrx(ser, cmd, wait)
            out.append(row)
            print(f"{cmd:>7} -> {row['text']}")

    Path("tc_diagnostics.json").write_text(json.dumps(out, indent=2), encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
