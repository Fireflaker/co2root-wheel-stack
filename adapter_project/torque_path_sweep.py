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
    return {
        "cmd": cmd,
        "ok": ("?;" not in text),
        "text": text,
        "raw_hex": raw.hex(),
    }


def run_case(ser: serial.Serial, name: str, um: int, rm: int | None, torque_cmd: str) -> dict:
    rows: list[dict] = []

    setup = [
        ("MO=0", 0.04),
        (f"UM={um}", 0.05),
        ("CL[1]=3", 0.04),
        ("CL[2]=3", 0.04),
    ]
    if rm is not None:
        setup.append((f"RM={rm}", 0.05))
    setup.extend(
        [
            ("UM", 0.04),
            ("RM", 0.04),
            ("MO=1", 0.05),
            ("BG", 0.05),
            ("PX", 0.04),
        ]
    )

    for cmd, wait in setup:
        rows.append(txrx(ser, cmd, wait))

    # Use a tiny command first, then observe status and position delta.
    rows.append(txrx(ser, torque_cmd, 0.08))
    rows.append(txrx(ser, "EC", 0.05))
    rows.append(txrx(ser, "SR", 0.05))
    rows.append(txrx(ser, "PX", 0.05))
    rows.append(txrx(ser, "TC=0", 0.04))
    rows.append(txrx(ser, "ST", 0.04))
    rows.append(txrx(ser, "MO=0", 0.04))

    first_px = None
    second_px = None
    for r in rows:
        if r["cmd"] == "PX":
            txt = r["text"]
            try:
                value = int(txt.split(";")[-2]) if ";" in txt else int(txt)
            except Exception:
                value = None
            if first_px is None:
                first_px = value
            else:
                second_px = value
                break

    return {
        "case": name,
        "um": um,
        "rm": rm,
        "torque_cmd": torque_cmd,
        "torque_cmd_ok": next((r["ok"] for r in rows if r["cmd"] == torque_cmd), False),
        "ec_after": next((r["text"] for r in rows if r["cmd"] == "EC"), ""),
        "sr_after": next((r["text"] for r in rows if r["cmd"] == "SR"), ""),
        "px_before": first_px,
        "px_after": second_px,
        "px_delta": (None if first_px is None or second_px is None else second_px - first_px),
        "rows": rows,
    }


def main() -> int:
    cases = [
        ("um1_rmNone_tc", 1, None, "TC=100"),
        ("um1_rm0_tc", 1, 0, "TC=100"),
        ("um1_rm1_tc", 1, 1, "TC=100"),
        ("um1_rm2_tc", 1, 2, "TC=100"),
        ("um1_rm1_iq", 1, 1, "IQ=100"),
        ("um1_rm1_il", 1, 1, "IL=100"),
        ("um4_rm1_tc", 4, 1, "TC=100"),
        ("um5_rm1_tc", 5, 1, "TC=100"),
    ]

    out: list[dict] = []
    with serial.Serial("COM13", 115200, timeout=0.2) as ser:
        time.sleep(0.12)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        for name, um, rm, torque_cmd in cases:
            result = run_case(ser, name, um, rm, torque_cmd)
            out.append(result)
            print(
                f"{name:16} um={um} rm={rm} cmd={torque_cmd:7} ok={result['torque_cmd_ok']} px_delta={result['px_delta']}"
            )

    Path("torque_path_sweep.json").write_text(json.dumps(out, indent=2), encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())