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
    text = raw.decode("ascii", errors="replace").strip()
    return {"cmd": cmd, "ok": ("?;" not in text), "text": text, "raw_hex": raw.hex()}


def qint(ser: serial.Serial, cmd: str) -> int | None:
    row = txrx(ser, cmd, 0.05)
    txt = row["text"]
    try:
        body = txt.split("\r", 1)[1]
        return int(body.split(";", 1)[0])
    except Exception:
        return None


def run_case(ser: serial.Serial, name: str, um: int, sequence: list[tuple[str, float]]) -> dict:
    rows: list[dict] = []
    rows.append(txrx(ser, "MO=0", 0.04))
    rows.append(txrx(ser, f"UM={um}", 0.05))
    rows.append(txrx(ser, "MO=1", 0.05))
    rows.append(txrx(ser, "UM", 0.04))

    p0 = qint(ser, "PX")
    for cmd, wait in sequence:
        rows.append(txrx(ser, cmd, wait))
    time.sleep(0.35)
    p1 = qint(ser, "PX")
    rows.append(txrx(ser, "EC", 0.05))
    rows.append(txrx(ser, "SR", 0.05))
    rows.append(txrx(ser, "ST", 0.04))
    rows.append(txrx(ser, "MO=0", 0.04))

    return {
        "case": name,
        "um": um,
        "p0": p0,
        "p1": p1,
        "px_delta": None if p0 is None or p1 is None else (p1 - p0),
        "rows": rows,
    }


def main() -> int:
    cases = [
        ("um2_jv_bg", 2, [("JV=600", 0.06), ("BG", 0.06)]),
        ("um2_jv_neg", 2, [("JV=-600", 0.06), ("BG", 0.06)]),
        ("um5_pa_bg", 5, [("PA=2000", 0.06), ("BG", 0.06)]),
        ("um5_pr_bg", 5, [("PR=2000", 0.06), ("BG", 0.06)]),
        ("um6_pa_bg", 6, [("PA=2000", 0.06), ("BG", 0.06)]),
        ("um6_pr_bg", 6, [("PR=2000", 0.06), ("BG", 0.06)]),
        ("um1_jv_bg", 1, [("JV=600", 0.06), ("BG", 0.06)]),
        ("um3_jv_bg", 3, [("JV=600", 0.06), ("BG", 0.06)]),
    ]

    out: list[dict] = []
    with serial.Serial("COM13", 115200, timeout=0.2) as ser:
        time.sleep(0.12)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        for name, um, seq in cases:
            row = run_case(ser, name, um, seq)
            out.append(row)
            print(f"{name:12} um={um} px_delta={row['px_delta']}")

    Path("motion_ref_discovery.json").write_text(json.dumps(out, indent=2), encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())