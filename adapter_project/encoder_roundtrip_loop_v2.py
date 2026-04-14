#!/usr/bin/env python3
"""
Robust encoder roundtrip validation loop with improved error handling.
Tests continuous CW/CCW one-revolution cycles with live encoder delta logging.
"""
from __future__ import annotations

import argparse
import re
import signal
import sys
import time
from dataclasses import dataclass

import serial


def parse_last_int(text: str) -> int | None:
    """Extract last integer from text."""
    nums = re.findall(r"-?\d+", text)
    return int(nums[-1]) if nums else None


def send(ser: serial.Serial, cmd: str, wait: float = 0.05) -> str:
    """Send command and read response."""
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 256)
    return raw.decode("ascii", errors="replace").strip()


def query_int(ser: serial.Serial, cmd: str, wait: float = 0.05) -> int | None:
    """Query integer value from drive."""
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
    """Wait for motion to complete and stabilize."""
    px0 = query_int(ser, "PX", wait=0.03)
    if px0 is None:
        print("    [WARN] Could not read initial PX", flush=True)
        return None, None, None

    t0 = time.time()
    reached = False
    stable_since: float | None = None
    last_px = px0

    while time.time() - t0 < timeout_s:
        try:
            px = query_int(ser, "PX", wait=0.03)
            if px is None:
                time.sleep(poll_s)
                continue

            delta = px - px0
            # Check if we've reached 90% of expected delta
            if abs(delta) >= max(1, int(expected_abs_delta * 0.90)):
                reached = True

            # Check for position stability
            if px == last_px:
                if stable_since is None:
                    stable_since = time.time()
            else:
                stable_since = None
                last_px = px

            # Return when reached AND stable
            if reached and stable_since is not None and (time.time() - stable_since) >= stable_window_s:
                return px0, px, delta

            time.sleep(poll_s)
        except Exception as e:
            print(f"    [WARN] Error in wait_until_stable: {e}", flush=True)
            time.sleep(poll_s)
            continue

    # Timeout: return best effort
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
        print("\n[STOP] Signal received, shutting down gracefully...", flush=True)
        state.running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(
        f"Starting encoder roundtrip loop v2 on {args.port} @ {args.baud} "
        f"(UM={args.um}, RM={args.rm}, counts_per_rev={args.counts_per_rev})",
        flush=True,
    )

    try:
        with serial.Serial(args.port, args.baud, timeout=0.25) as ser:
            time.sleep(0.12)
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass

            # Setup sequence
            send(ser, "ST", wait=0.04)
            send(ser, "TC=0", wait=0.02)
            send(ser, "MO=0", wait=0.04)
            send(ser, f"UM={args.um}", wait=0.05)
            send(ser, f"RM={args.rm}", wait=0.05)
            send(ser, "MO=1", wait=0.05)

            mo = query_int(ser, "MO", wait=0.04)
            um = query_int(ser, "UM", wait=0.04)
            print(f"Drive state: MO={mo} UM={um}", flush=True)
            print("--- Starting cycles ---", flush=True)

            cycle_count = 0
            error_count = 0

            while state.running:
                try:
                    direction = 1 if (cycle_count % 2) == 0 else -1
                    name = "CW" if direction > 0 else "CCW"
                    cmd_counts = direction * args.counts_per_rev

                    # Send motion commands
                    send(ser, f"PR={cmd_counts}", wait=0.01)
                    send(ser, "BG", wait=0.01)

                    # Wait for completion
                    px0, px1, delta = wait_until_stable(
                        ser,
                        expected_abs_delta=args.counts_per_rev,
                        timeout_s=args.timeout_s,
                        stable_window_s=args.settle_s,
                        poll_s=args.poll_s,
                    )

                    # Validation
                    ok = (delta is not None) and (abs(abs(delta) - args.counts_per_rev) <= int(args.counts_per_rev * 0.15))
                    
                    print(
                        f"[{cycle_count:04d}] {name:>3} cmd={cmd_counts:+d} px0={px0} px1={px1} "
                        f"delta={delta} target={args.counts_per_rev} ok={ok}",
                        flush=True,
                    )

                    if not ok:
                        error_count += 1
                        if error_count >= 3:
                            print(f"[ERROR] 3 consecutive validation failures, stopping loop", flush=True)
                            break

                    cycle_count += 1

                except Exception as e:
                    print(f"[ERROR] Cycle error: {e}", flush=True)
                    error_count += 1
                    if error_count >= 3:
                        print(f"[ERROR] Too many errors, stopping", flush=True)
                        break
                    time.sleep(0.5)  # Brief pause before retry

            # Safe shutdown
            print("[SHUTDOWN] Sending stop sequence...", flush=True)
            send(ser, "ST", wait=0.04)
            send(ser, "TC=0", wait=0.02)
            send(ser, "MO=0", wait=0.04)
            print(f"[COMPLETE] Ran {cycle_count} cycles, {error_count} errors. Sent ST, TC=0, MO=0", flush=True)

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Keyboard interrupt received", flush=True)
        return 1
    except serial.SerialException as e:
        print(f"[SERIAL ERROR] {e}", flush=True)
        return 1
    except Exception as e:
        print(f"[FATAL ERROR] {e}", flush=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
