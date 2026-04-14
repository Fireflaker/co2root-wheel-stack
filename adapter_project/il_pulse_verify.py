#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import serial


def txrx(ser: serial.Serial, cmd: str, wait: float = 0.05) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 256)
    return raw.decode("ascii", errors="replace").strip()


def query_int(ser: serial.Serial, cmd: str, wait: float = 0.05) -> int | None:
    txt = txrx(ser, cmd, wait)
    try:
        # Typical format is: PX\r12345;
        body = txt.split("\r", 1)[1]
        value = body.split(";", 1)[0]
        return int(value)
    except Exception:
        return None


def main() -> int:
    amp = int(sys.argv[1]) if len(sys.argv) > 1 else 700
    hold_s = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35

    out: dict = {"steps": []}

    with serial.Serial("COM13", 115200, timeout=0.2) as ser:
        time.sleep(0.12)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        for cmd in ["MO=0", "UM=1", "RM=1", "CL[1]=3", "CL[2]=3", "MO=1", "UM", "RM", "EC"]:
            out["steps"].append({"cmd": cmd, "resp": txrx(ser, cmd, 0.05)})

        p0 = query_int(ser, "PX", 0.05)
        out["p0"] = p0

        # Controlled, short pulses to confirm bidirectional movement.
        out["steps"].append({"cmd": f"IL={amp}", "resp": txrx(ser, f"IL={amp}", 0.06)})
        time.sleep(hold_s)
        p1 = query_int(ser, "PX", 0.05)

        out["steps"].append({"cmd": f"IL={-amp}", "resp": txrx(ser, f"IL={-amp}", 0.06)})
        time.sleep(hold_s)
        p2 = query_int(ser, "PX", 0.05)

        out["steps"].append({"cmd": "IL=0", "resp": txrx(ser, "IL=0", 0.05)})
        out["steps"].append({"cmd": "EC", "resp": txrx(ser, "EC", 0.05)})
        out["steps"].append({"cmd": "SR", "resp": txrx(ser, "SR", 0.05)})
        out["steps"].append({"cmd": "MO=0", "resp": txrx(ser, "MO=0", 0.05)})

    out["p1"] = p1
    out["p2"] = p2
    out["delta_pos"] = None if p0 is None or p1 is None else (p1 - p0)
    out["delta_neg"] = None if p1 is None or p2 is None else (p2 - p1)
    out["moved"] = bool((out["delta_pos"] and abs(out["delta_pos"]) > 10) or (out["delta_neg"] and abs(out["delta_neg"]) > 10))

    Path("il_pulse_verify.json").write_text(json.dumps(out, indent=2), encoding="ascii")
    print(json.dumps({
        "amp": amp,
        "hold_s": hold_s,
        "p0": p0,
        "p1": p1,
        "p2": p2,
        "delta_pos": out["delta_pos"],
        "delta_neg": out["delta_neg"],
        "moved": out["moved"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())