#!/usr/bin/env python3
"""
High-frequency encoder polling for racing sim wheels.
Reads encoder at ~1000Hz (1ms), outputs 16-bit downscaled angle.

Formula: 16-bit = (raw_counts >> 5) & 0xFFFF
Converts 2,097,152 counts/rev -> 65,536 steps (0-65535 wraps at 360°)
"""
from __future__ import annotations

import argparse
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial


def parse_last_int(text: str) -> int | None:
    """Extract last integer from text."""
    nums = re.findall(r"-?\d+", text)
    return int(nums[-1]) if nums else None


def send(ser: serial.Serial, cmd: str, wait: float = 0.02) -> str:
    """Send command and read response (non-blocking friendly)."""
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 256)
    return raw.decode("ascii", errors="replace").strip()


def query_int(ser: serial.Serial, cmd: str, wait: float = 0.02) -> int | None:
    """Query integer value."""
    return parse_last_int(send(ser, cmd, wait=wait))


@dataclass
class PollerState:
    running: bool = True
    last_angle_16bit: int = 0
    last_raw: int | None = None
    sample_count: int = 0
    error_count: int = 0


def counts_to_16bit(raw_counts: int | None) -> int:
    """Convert raw encoder counts to 16-bit (0-65535) representation.
    
    2,097,152 counts/rev = 2^21
    16-bit output = 2^16 = 65,536 steps
    Right-shift by 5 bits to downscale: (2^21 >> 5) = 2^16
    Mask to 16-bit: & 0xFFFF (wraps cleanly)
    """
    if raw_counts is None:
        return 0
    # Handle negative counts by wrapping to positive
    wrapped = raw_counts & 0x007FFFFF  # Mask to 21 bits for wraparound
    angle_16bit = (wrapped >> 5) & 0xFFFF
    return angle_16bit


def polling_worker(ser: serial.Serial, state: PollerState, output_fn: Callable[[int, int], None]) -> None:
    """Background thread: poll PX at ~1000Hz, compute 16-bit angle, call output_fn(angle, raw)."""
    cycle_time = 0.001  # 1ms for 1000Hz
    
    while state.running:
        try:
            t0 = time.perf_counter()
            
            # Query encoder position
            raw = query_int(ser, "PX", wait=0.001)
            angle_16bit = counts_to_16bit(raw)
            
            state.last_angle_16bit = angle_16bit
            state.last_raw = raw
            state.sample_count += 1
            
            # Callback for output
            output_fn(angle_16bit, raw)
            
            # Sleep to maintain ~1kHz rate
            elapsed = time.perf_counter() - t0
            sleep_time = max(0, cycle_time - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        except Exception as e:
            state.error_count += 1
            if state.error_count < 10:  # Only log first 10 errors
                print(f"[POLL ERROR] {e}", flush=True)
            time.sleep(0.001)


def main() -> int:
    p = argparse.ArgumentParser(
        description="High-frequency encoder polling for racing sim wheels (1000Hz, 16-bit output)"
    )
    p.add_argument("--port", default="COM13")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--mode", default="live", choices=["live", "json", "csv"],
                  help="Output format: live (human), json (per-line), csv (streaming)")
    p.add_argument("--duration", type=float, default=0.0,
                  help="Run for N seconds (0=infinite)")
    args = p.parse_args()

    state = PollerState(True)

    def _stop(*_):
        state.running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(
        f"[START] Encoder poller on {args.port} @ {args.baud} baud (1000Hz, 16-bit)\n"
        f"[INFO] Bit-shift: (raw >> 5) & 0xFFFF | 2M→65K counts\n"
        f"[INFO] Output: {args.mode} | Ctrl+C to stop",
        flush=True
    )

    try:
        with serial.Serial(args.port, args.baud, timeout=0.05) as ser:
            time.sleep(0.12)
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except:
                pass

            # Setup drive
            send(ser, "ST", wait=0.02)
            send(ser, "TC=0", wait=0.02)
            send(ser, "MO=0", wait=0.02)
            send(ser, "UM=5", wait=0.05)
            send(ser, "MO=1", wait=0.05)

            # Get initial position
            px_init = query_int(ser, "PX", wait=0.05)
            print(f"[READY] Initial PX={px_init}", flush=True)

            # Define output callback based on mode
            if args.mode == "live":
                def output_live(angle_16bit: int, raw: int):
                    # Sparse output for readability
                    if state.sample_count % 100 == 0:  # Every 100ms
                        pct = (angle_16bit / 65536.0) * 360.0
                        print(f"[{state.sample_count:06d}] angle={angle_16bit:5d} ({pct:6.1f}°) raw={raw}", flush=True)
                output_fn = output_live
            
            elif args.mode == "json":
                def output_json(angle_16bit: int, raw: int):
                    import json
                    line = json.dumps({"t": state.sample_count, "angle": angle_16bit, "raw": raw})
                    print(line, flush=True)
                output_fn = output_json
            
            else:  # csv
                def output_csv(angle_16bit: int, raw: int):
                    if state.sample_count == 1:
                        print("sample_num,angle_16bit,raw_counts", flush=True)
                    if state.sample_count % 10 == 0:  # Every 10ms
                        print(f"{state.sample_count},{angle_16bit},{raw}", flush=True)
                output_fn = output_csv

            # Start background poller thread
            poller_thread = threading.Thread(target=polling_worker, args=(ser, state, output_fn), daemon=True)
            poller_thread.start()

            # Main thread: monitor and optionally limit duration
            t_start = time.time()
            while state.running:
                if args.duration > 0 and (time.time() - t_start) > args.duration:
                    print(f"\n[DURATION] Reached {args.duration}s, stopping", flush=True)
                    state.running = False
                    break
                time.sleep(0.1)

            # Wait for poller to finish
            poller_thread.join(timeout=1.0)

            # Shutdown
            print(f"\n[SHUTDOWN] Sending stop commands...", flush=True)
            send(ser, "ST", wait=0.02)
            send(ser, "TC=0", wait=0.02)
            send(ser, "MO=0", wait=0.02)

            elapsed = time.time() - t_start
            rate = state.sample_count / elapsed if elapsed > 0 else 0
            print(
                f"[COMPLETE] Ran {state.sample_count} samples in {elapsed:.2f}s "
                f"({rate:.0f} Hz) | Errors: {state.error_count}",
                flush=True
            )

    except serial.SerialException as e:
        print(f"[SERIAL ERROR] {e}", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Keyboard interrupt", flush=True)
        return 0
    except Exception as e:
        print(f"[FATAL ERROR] {e}", flush=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
