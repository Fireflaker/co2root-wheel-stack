#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import serial


def parse_last_int(text: str) -> Optional[int]:
    m = re.findall(r"-?\d+", text)
    return int(m[-1]) if m else None


def send(ser: serial.Serial, cmd: str, wait: float = 0.04) -> str:
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    return ser.read(ser.in_waiting or 256).decode("ascii", errors="replace").strip()


def main() -> int:
    report: list[dict] = []
    with serial.Serial("COM13", 115200, timeout=0.2) as ser:
        time.sleep(0.12)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        for um in range(0, 12):
            row: dict = {"um": um}
            row["mo0"] = send(ser, "MO=0")
            row["set_um"] = send(ser, f"UM={um}")
            row["read_um"] = send(ser, "UM")
            row["mo1"] = send(ser, "MO=1")

            px_before = parse_last_int(send(ser, "PX"))
            tc_pos = send(ser, "TC=250", wait=0.0)
            time.sleep(0.35)
            px_mid = parse_last_int(send(ser, "PX"))
            tc_zero = send(ser, "TC=0", wait=0.0)

            row["tc_pos"] = tc_pos
            row["tc_zero"] = tc_zero
            row["px_before"] = px_before
            row["px_mid"] = px_mid
            row["px_delta"] = abs(px_mid - px_before) if px_before is not None and px_mid is not None else None
            row["tc_accepted"] = "?;" not in tc_pos
            report.append(row)

    out = Path("um_tc_discovery.json")
    out.write_text(json.dumps(report, indent=2), encoding="ascii")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
