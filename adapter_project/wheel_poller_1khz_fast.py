#!/usr/bin/env python3
"""
Optimized high-frequency encoder poller for racing sim wheels.
Uses non-blocking serial reads and faster query intervals.
Target: 1000Hz (1ms) or best-effort given 115200 baud constraints.

Bit-shift formula: 16-bit angle = (raw_counts >> 5) & 0xFFFF
Converts 2,097,152 counts/rev → 65,536 steps (0-65535 = 360°)
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


def parse_all_ints(text: str) -> list[int]:
    """Extract all integers from text."""
    nums = re.findall(r"-?\d+", text)
    return [int(n) for n in nums]


def extract_px(response: str) -> int | None:
    """Extract PX value from response (handles multi-line buffering)."""
    # Response format: ">PX\r\n{value};\r\n>"
    nums = parse_all_ints(response)
    return nums[-1] if nums else None


def counts_to_16bit(raw_counts: int | None) -> int:
    """Convert raw encoder counts to 16-bit angle (0-65535).
    
    2,097,152 counts/rev = 2^21
    Downshift to 16-bit: (counts >> 5) & 0xFFFF
    """
    if raw_counts is None:
        return 0
    wrapped = raw_counts & 0x007FFFFF  # 21-bit wrap
    return (wrapped >> 5) & 0xFFFF


@dataclass
class PollerState:
    running: bool = True
    last_angle_16bit: int = 0
    last_raw: int | None = None
    sample_count: int = 0
    error_count: int = 0


def polling_worker(ser: serial.Serial, state: PollerState, output_fn: Callable) -> None:
    """Background: Poll PX continuously, output 16-bit angles."""
    poll_interval = 0.001  # Target 1ms between queries
    
    while state.running:
        try:
            t0 = time.perf_counter()
            
            # Send PX query
            ser.write(b"PX\r")
            ser.flush()
            
            # Wait brief moment for response
            time.sleep(0.0005)  # 0.5ms for response
            
            # Read all available bytes (may include prompt)
            response = ""
            while ser.in_waiting > 0:
                response += ser.read(ser.in_waiting).decode("ascii", errors="replace")
            
            # Extract PX value
            raw = extract_px(response)
            if raw is not None:
                angle_16bit = counts_to_16bit(raw)
                state.last_angle_16bit = angle_16bit
                state.last_raw = raw
                state.sample_count += 1
                output_fn(angle_16bit, raw, state.sample_count)
            
            # Sleep to maintain interval
            elapsed = time.perf_counter() - t0
            sleep_time = max(0.0001, poll_interval - elapsed)
            time.sleep(sleep_time)
        
        except Exception as e:
            state.error_count += 1
            if state.error_count < 5:
                print(f"[POLL ERROR] {e}", flush=True)
            time.sleep(0.001)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Optimized 1000Hz encoder poller for racing sim wheels (16-bit output)"
    )
    p.add_argument("--port", default="COM13")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--mode", default="live", choices=["live", "json", "csv"])
    p.add_argument("--duration", type=float, default=0.0, help="Run for N seconds (0=infinite)")
    args = p.parse_args()

    state = PollerState(True)

    def _stop(*_):
        state.running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(
        f"[START] Optimized encoder poller | {args.port} @ {args.baud} | 1000Hz target, 16-bit output\n"
        f"[TECH]  Bit-shift (>> 5) & 0xFFFF maps 2M→65K counts\n"
        f"[MODE]  {args.mode} | Ctrl+C to stop",
        flush=True
    )

    try:
        with serial.Serial(args.port, args.baud, timeout=0.01) as ser:
            time.sleep(0.12)
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except:
                pass

            # Initialize drive
            ser.write(b"ST\r")
            ser.flush()
            time.sleep(0.02)
            ser.read(ser.in_waiting or 256)  # Clear

            ser.write(b"MO=0\r")
            ser.flush()
            time.sleep(0.02)
            ser.read(ser.in_waiting or 256)

            ser.write(b"UM=5\r")
            ser.flush()
            time.sleep(0.05)
            ser.read(ser.in_waiting or 256)

            ser.write(b"MO=1\r")
            ser.flush()
            time.sleep(0.05)
            ser.read(ser.in_waiting or 256)

            # Get initial position
            ser.write(b"PX\r")
            ser.flush()
            time.sleep(0.05)
            init_resp = ""
            while ser.in_waiting > 0:
                init_resp += ser.read(ser.in_waiting).decode("ascii", errors="replace")
            px_init = extract_px(init_resp)
            print(f"[INIT]  PX={px_init}", flush=True)

            # Output callback
            if args.mode == "live":
                def output_live(angle_16bit: int, raw: int, sample_count: int):
                    if sample_count % 50 == 0:  # Every 50ms at 1kHz
                        deg = (angle_16bit / 65536.0) * 360.0
                        print(f"[{sample_count:06d}] angle={angle_16bit:5d} ({deg:6.1f}°) raw={raw}", flush=True)
                output_fn = output_live

            elif args.mode == "json":
                import json
                def output_json(angle_16bit: int, raw: int, sample_count: int):
                    line = json.dumps({"n": sample_count, "angle": angle_16bit, "raw": raw})
                    print(line, flush=True)
                output_fn = output_json

            else:  # csv
                def output_csv(angle_16bit: int, raw: int, sample_count: int):
                    if sample_count == 1:
                        print("sample,angle_16bit,raw_counts", flush=True)
                    if sample_count % 10 == 0:  # Every 10ms
                        print(f"{sample_count},{angle_16bit},{raw}", flush=True)
                output_fn = output_csv

            # Start poller thread
            poller = threading.Thread(target=polling_worker, args=(ser, state, output_fn), daemon=True)
            poller.start()

            # Main loop
            t_start = time.time()
            while state.running:
                if args.duration > 0 and (time.time() - t_start) > args.duration:
                    print(f"\n[STOP]  Duration {args.duration}s reached", flush=True)
                    state.running = False
                time.sleep(0.05)

            poller.join(timeout=1.0)

            # Shutdown
            ser.write(b"ST\r")
            ser.flush()
            time.sleep(0.02)
            ser.write(b"TC=0\r")
            ser.flush()
            time.sleep(0.02)
            ser.write(b"MO=0\r")
            ser.flush()

            elapsed = time.time() - t_start
            rate = state.sample_count / elapsed if elapsed > 0 else 0
            print(
                f"[DONE]  {state.sample_count} samples in {elapsed:.2f}s → {rate:.0f} Hz | "
                f"Errors: {state.error_count}",
                flush=True
            )

    except serial.SerialException as e:
        print(f"[SERIAL ERROR] {e}", flush=True)
        return 1
    except Exception as e:
        print(f"[ERROR] {e}", flush=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
