#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import signal
import time
from dataclasses import dataclass

import serial


def parse_last_int(text: str) -> int | None:
    nums = re.findall(r"-?\d+", text)
    return int(nums[-1]) if nums else None


def send(ser: serial.Serial, cmd: str, wait: float = 0.05) -> str:
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 256)
    return raw.decode("ascii", errors="replace").strip()


def query_int(ser: serial.Serial, cmd: str, wait: float = 0.05) -> int | None:
    return parse_last_int(send(ser, cmd, wait=wait))


@dataclass
class LoopState:
    running: bool = True


def wait_until_stable(
    ser: serial.Serial,
    expected_abs_delta: int,
    timeout_s: float,
    stable_window_s: float,
    poll_s: float,
) -> tuple[int | None, int | None, int | None]:
    px0 = query_int(ser, "PX", wait=0.03)
    if px0 is None:
        return None, None, None

    t0 = time.time()
    reached = False
    stable_since: float | None = None
    last_px = px0

    while time.time() - t0 < timeout_s:
        px = query_int(ser, "PX", wait=0.03)
        if px is None:
            time.sleep(poll_s)
            continue

        delta = px - px0
        if abs(delta) >= max(1, int(expected_abs_delta * 0.90)):
            reached = True

        if px == last_px:
            if stable_since is None:
                stable_since = time.time()
        else:
            stable_since = None
            last_px = px

        if reached and stable_since is not None and (time.time() - stable_since) >= stable_window_s:
            return px0, px, delta

        time.sleep(poll_s)

    px_end = query_int(ser, "PX", wait=0.03)
    return px0, px_end, (None if px_end is None else px_end - px0)


def main() -> int:
    p = argparse.ArgumentParser(description="Continuous +1/-1 turn encoder verification loop.")
    p.add_argument("--port", default="COM13")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--um", type=int, default=5)
    p.add_argument("--rm", type=int, default=1)
    p.add_argument("--counts-per-rev", type=int, default=131072)
    p.add_argument("--timeout-s", type=float, default=25.0)
    p.add_argument("--settle-s", type=float, default=0.45)
    p.add_argument("--poll-s", type=float, default=0.06)
    args = p.parse_args()

    state = LoopState(True)

    def _stop(*_):
        state.running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(
        f"Starting encoder roundtrip loop on {args.port} @ {args.baud} "
        f"(UM={args.um}, RM={args.rm}, counts_per_rev={args.counts_per_rev})",
        flush=True,
    )

    with serial.Serial(args.port, args.baud, timeout=0.25) as ser:
        time.sleep(0.12)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        send(ser, "ST", wait=0.04)
        send(ser, "TC=0", wait=0.02)
        send(ser, "MO=0", wait=0.04)
        send(ser, f"UM={args.um}", wait=0.05)
        send(ser, f"RM={args.rm}", wait=0.05)
        send(ser, "MO=1", wait=0.05)

        mo = query_int(ser, "MO", wait=0.04)
        um = query_int(ser, "UM", wait=0.04)
        print(f"Drive state: MO={mo} UM={um}", flush=True)

        seq = [
            (+1, "CW"),
            (-1, "CCW"),
        ]
        i = 0
        while state.running:
            direction, name = seq[i % 2]
            i += 1
            cmd_counts = direction * args.counts_per_rev

            send(ser, f"PR={cmd_counts}", wait=0.01)
            send(ser, "BG", wait=0.01)

            px0, px1, delta = wait_until_stable(
                ser,
                expected_abs_delta=args.counts_per_rev,
                timeout_s=args.timeout_s,
                stable_window_s=args.settle_s,
                poll_s=args.poll_s,
            )

            ok = (delta is not None) and (abs(abs(delta) - args.counts_per_rev) <= int(args.counts_per_rev * 0.15))
            print(
                f"{name:>3} cmd={cmd_counts:+d} px0={px0} px1={px1} delta={delta} "
                f"target={args.counts_per_rev} ok={ok}",
                flush=True,
            )

        # Safe shutdown on exit.
        send(ser, "ST", wait=0.04)
        send(ser, "TC=0", wait=0.02)
        send(ser, "MO=0", wait=0.04)
        print("Stopped. Sent ST, TC=0, MO=0", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
