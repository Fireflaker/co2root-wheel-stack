#!/usr/bin/env python3
from __future__ import annotations

import time
import serial

PORT = "COM13"
BAUD = 115200


def txrx(ser: serial.Serial, cmd: str, wait: float = 0.08) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 256)
    txt = raw.decode("ascii", errors="replace").strip()
    return txt


def main() -> int:
    print(f"Opening {PORT} @ {BAUD}")
    with serial.Serial(PORT, BAUD, timeout=0.25) as ser:
        time.sleep(0.15)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        for cmd in ["MO", "UM", "SR", "EC", "PX"]:
            print(f"Q {cmd:>2}: {txrx(ser, cmd)}")

        print("\nSending hard release sequence...")
        for cmd in ["ST", "TC=0", "MO=0", "MO=0", "ST"]:
            print(f"C {cmd:>4}: {txrx(ser, cmd)}")
            time.sleep(0.06)

        print("\nPost-release readback:")
        for cmd in ["MO", "UM", "SR", "EC", "PX"]:
            print(f"Q {cmd:>2}: {txrx(ser, cmd)}")

        print("\nWait 2s and re-check MO (detect auto re-enable)...")
        time.sleep(2.0)
        print(f"Q MO : {txrx(ser, 'MO')}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
