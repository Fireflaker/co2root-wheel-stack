#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import serial


def parse_last_int(text: str) -> Optional[int]:
    nums = re.findall(r"-?\d+", text)
    return int(nums[-1]) if nums else None


def send(ser: serial.Serial, cmd: str, wait: float = 0.05) -> str:
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    return ser.read(ser.in_waiting or 256).decode("ascii", errors="replace").strip()


def run() -> dict:
    rep = {"port": "COM13", "baud": 115200, "runs": []}
    with serial.Serial("COM13", 115200, timeout=0.2) as ser:
        time.sleep(0.12)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        rep["initial"] = {"UM": send(ser, "UM"), "MO": send(ser, "MO"), "PX": send(ser, "PX")}

        v = {"mode": "UM=2 velocity", "commands": {}, "px_before": None, "px_mid": None, "px_after": None, "px_delta": None}
        v["commands"]["MO=0"] = send(ser, "MO=0")
        v["commands"]["UM=2"] = send(ser, "UM=2")
        v["commands"]["MO=1"] = send(ser, "MO=1")
        v["px_before"] = parse_last_int(send(ser, "PX"))

        v["commands"]["JV=2500"] = send(ser, "JV=2500")
        v["commands"]["BG(+)"] = send(ser, "BG")
        time.sleep(1.5)
        v["px_mid"] = parse_last_int(send(ser, "PX"))

        v["commands"]["ST(1)"] = send(ser, "ST")
        v["commands"]["JV=-2500"] = send(ser, "JV=-2500")
        v["commands"]["BG(-)"] = send(ser, "BG")
        time.sleep(1.5)

        v["commands"]["ST(2)"] = send(ser, "ST")
        v["commands"]["JV=0"] = send(ser, "JV=0")
        v["commands"]["BG(0)"] = send(ser, "BG")
        time.sleep(0.2)

        v["px_after"] = parse_last_int(send(ser, "PX"))
        if v["px_before"] is not None and v["px_mid"] is not None:
            v["px_delta"] = abs(v["px_mid"] - v["px_before"])
        rep["runs"].append(v)

        t = {"mode": "UM=5 torque", "commands": {}, "px_before": None, "px_mid": None, "px_after": None, "px_delta": None}
        t["commands"]["MO=0"] = send(ser, "MO=0")
        t["commands"]["UM=5"] = send(ser, "UM=5")
        t["commands"]["MO=1"] = send(ser, "MO=1")
        t["px_before"] = parse_last_int(send(ser, "PX"))

        t["commands"]["TC=350"] = send(ser, "TC=350", wait=0.0)
        time.sleep(0.8)
        t["px_mid"] = parse_last_int(send(ser, "PX"))
        t["commands"]["TC=-350"] = send(ser, "TC=-350", wait=0.0)
        time.sleep(0.8)
        t["commands"]["TC=0"] = send(ser, "TC=0", wait=0.0)
        time.sleep(0.15)

        t["px_after"] = parse_last_int(send(ser, "PX"))
        if t["px_before"] is not None and t["px_mid"] is not None:
            t["px_delta"] = abs(t["px_mid"] - t["px_before"])
        rep["runs"].append(t)

        u4 = {"mode": "UM=4 torque", "commands": {}, "px_before": None, "px_mid": None, "px_after": None, "px_delta": None}
        u4["commands"]["MO=0"] = send(ser, "MO=0")
        u4["commands"]["UM=4"] = send(ser, "UM=4")
        u4["commands"]["MO=1"] = send(ser, "MO=1")
        u4["px_before"] = parse_last_int(send(ser, "PX"))

        u4["commands"]["TC=350"] = send(ser, "TC=350", wait=0.0)
        time.sleep(0.8)
        u4["px_mid"] = parse_last_int(send(ser, "PX"))
        u4["commands"]["TC=-350"] = send(ser, "TC=-350", wait=0.0)
        time.sleep(0.8)
        u4["commands"]["TC=0"] = send(ser, "TC=0", wait=0.0)
        time.sleep(0.15)

        u4["px_after"] = parse_last_int(send(ser, "PX"))
        if u4["px_before"] is not None and u4["px_mid"] is not None:
            u4["px_delta"] = abs(u4["px_mid"] - u4["px_before"])
        rep["runs"].append(u4)

        rep["final"] = {"UM": send(ser, "UM"), "MO": send(ser, "MO"), "PX": send(ser, "PX")}

    return rep


def main() -> int:
    rep = run()
    out = Path("direct_rotation_sweep.json")
    out.write_text(json.dumps(rep, indent=2), encoding="ascii")
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
