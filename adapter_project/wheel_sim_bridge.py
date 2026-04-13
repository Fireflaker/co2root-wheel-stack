#!/usr/bin/env python3
"""
Racing Sim Wheel Bridge: Connects encoder to game controller input.
Supports vJoy (universal gamepad) or UDP telemetry output.

Usage:
  python wheel_sim_bridge.py --mode vjoy  (native sim support)
  python wheel_sim_bridge.py --mode udp --host 127.0.0.1 --port 5005  (network)
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial

try:
    import pyvjoy
    VJOY_AVAILABLE = True
except ImportError:
    VJOY_AVAILABLE = False
    print("[WARN] pyvjoy not installed - UDP mode only. Install: pip install pyvjoy")


def parse_all_ints(text: str) -> list[int]:
    """Extract all integers from text."""
    import re
    nums = re.findall(r"-?\d+", text)
    return [int(n) for n in nums]


def extract_px(response: str) -> int | None:
    """Extract PX value from response."""
    nums = parse_all_ints(response)
    return nums[-1] if nums else None


def counts_to_16bit(raw_counts: int | None) -> int:
    """Convert raw encoder counts to 16-bit angle (0-65535)."""
    if raw_counts is None:
        return 0
    wrapped = raw_counts & 0x007FFFFF
    return (wrapped >> 5) & 0xFFFF


def angle_to_steering_axis(angle_16bit: int) -> float:
    """Convert 16-bit angle (0-65535) to steering axis (-1.0 to +1.0).
    
    0 = hard left (-1.0)
    32768 = center (0.0)
    65535 = hard right (~+1.0)
    """
    # Map 0-65535 to -1.0 to +1.0
    normalized = (angle_16bit / 65535.0) * 2.0 - 1.0
    return max(-1.0, min(1.0, normalized))


@dataclass
class BridgeState:
    running: bool = True
    last_angle_16bit: int = 0
    last_steering: float = 0.0
    center_angle_16bit: int | None = None
    sample_count: int = 0
    error_count: int = 0


class vJoyBridge:
    """Output steering to vJoy virtual joystick."""
    
    def __init__(self, joystick_id: int = 1):
        if not VJOY_AVAILABLE:
            raise RuntimeError("pyvjoy not available - install: pip install pyvjoy")
        self.joystick = pyvjoy.VJoyDevice(joystick_id)
        self._neutralize_non_steering_axes()
        print(f"[vJOY] Initialized joystick ID={joystick_id}", flush=True)

    def _set_axis_safe(self, usage: int, value: int) -> None:
        try:
            self.joystick.set_axis(usage, value)
        except Exception:
            # Some devices expose a subset of axes; ignore unsupported ones.
            pass

    def _neutralize_non_steering_axes(self) -> None:
        # Keep steering-type axes centered and pedal-style axes released.
        center = 16384
        released = 0
        self._set_axis_safe(pyvjoy.HID_USAGE_X, center)
        self._set_axis_safe(pyvjoy.HID_USAGE_Y, center)
        self._set_axis_safe(pyvjoy.HID_USAGE_RX, center)
        self._set_axis_safe(pyvjoy.HID_USAGE_RY, center)
        self._set_axis_safe(pyvjoy.HID_USAGE_Z, released)
        self._set_axis_safe(pyvjoy.HID_USAGE_RZ, released)
        self._set_axis_safe(pyvjoy.HID_USAGE_SL0, released)
        self._set_axis_safe(pyvjoy.HID_USAGE_SL1, released)
    
    def update(self, steering: float) -> None:
        """Set steering axis (-1.0 to +1.0)."""
        # vJoy axis range: 0-32767 (center at 16384)
        axis_value = int(16384 + (steering * 16384))
        axis_value = max(0, min(32767, axis_value))
        self._set_axis_safe(pyvjoy.HID_USAGE_X, axis_value)
    
    def close(self) -> None:
        """Reset joystick."""
        self._neutralize_non_steering_axes()


def angle_to_centered_steering(angle_16bit: int, center_angle_16bit: int) -> float:
    """Convert absolute 16-bit angle to centered steering (-1.0 to +1.0)."""
    delta = ((angle_16bit - center_angle_16bit + 32768) & 0xFFFF) - 32768
    normalized = delta / 32767.0
    return max(-1.0, min(1.0, normalized))


class UDPBridge:
    """Output steering via UDP for network sims."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 5005):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = (host, port)
        print(f"[UDP] Binding to {host}:{port}", flush=True)
    
    def update(self, angle_16bit: int, steering: float, raw: int) -> None:
        """Send steering packet."""
        # JSON format: easy to parse in game mods
        data = {
            "timestamp": time.time(),
            "steering_angle_norm": steering,  # -1.0 to +1.0
            "steering_angle_raw": angle_16bit,  # 0-65535
            "encoder_counts": raw,
        }
        try:
            self.socket.sendto(json.dumps(data).encode(), self.addr)
        except Exception as e:
            print(f"[UDP ERROR] {e}", flush=True)
    
    def close(self) -> None:
        """Close socket."""
        self.socket.close()


def polling_worker(ser: serial.Serial, state: BridgeState, output_bridge: object, mode: str) -> None:
    """Background: Poll encoder, output to game."""
    poll_interval = 0.001  # 1ms for 1000Hz target
    
    while state.running:
        try:
            t0 = time.perf_counter()
            
            # Query encoder
            ser.write(b"PX\r")
            ser.flush()
            time.sleep(0.0005)
            
            response = ""
            while ser.in_waiting > 0:
                response += ser.read(ser.in_waiting).decode("ascii", errors="replace")
            
            raw = extract_px(response)
            if raw is not None:
                angle_16bit = counts_to_16bit(raw)
                if state.center_angle_16bit is None:
                    state.center_angle_16bit = angle_16bit
                    print(f"[CAL] Auto-center set to angle={angle_16bit}", flush=True)
                steering = angle_to_centered_steering(angle_16bit, state.center_angle_16bit)
                
                state.last_angle_16bit = angle_16bit
                state.last_steering = steering
                state.sample_count += 1
                
                # Update game controller
                if mode == "vjoy":
                    output_bridge.update(steering)
                elif mode == "udp":
                    output_bridge.update(angle_16bit, steering, raw)
            
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
        description="Racing Sim Wheel Bridge - Encoder → Game Controller"
    )
    p.add_argument("--port", default="COM13")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--mode", default="vjoy", choices=["vjoy", "udp"],
                  help="vjoy=virtual joystick (default), udp=network stream")
    p.add_argument("--vjoy-id", type=int, default=1, help="vJoy device ID")
    p.add_argument("--udp-host", default="127.0.0.1", help="UDP destination host")
    p.add_argument("--udp-port", type=int, default=5005, help="UDP destination port")
    p.add_argument(
        "--center-angle-16bit",
        type=int,
        default=None,
        help="Optional fixed center angle (0-65535). If omitted, first valid sample is used.",
    )
    p.add_argument(
        "--enable-motor",
        action="store_true",
        help="Enable motor output (MO=1). Default is OFF for safe read-only steering input.",
    )
    args = p.parse_args()

    state = BridgeState(True)
    if args.center_angle_16bit is not None:
        state.center_angle_16bit = int(args.center_angle_16bit) & 0xFFFF

    def _stop(*_):
        state.running = False

    import signal
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Initialize bridge
    use_vjoy = args.mode == "vjoy"
    if use_vjoy and not VJOY_AVAILABLE:
        print("[ERROR] vJoy mode selected but pyvjoy not installed")
        print("[INFO] Install: pip install pyvjoy")
        return 1

    try:
        # Create output bridge
        if use_vjoy:
            output_bridge = vJoyBridge(joystick_id=args.vjoy_id)
        else:
            output_bridge = UDPBridge(host=args.udp_host, port=args.udp_port)
        
        print(
            f"[START] Racing Sim Wheel Bridge\n"
            f"[PORT] {args.port} @ {args.baud} baud\n"
            f"[MODE] {args.mode.upper()}\n"
            f"[INFO] Steering: -1.0 (left) to +1.0 (right) | MotorEnable={args.enable_motor} | Ctrl+C to stop",
            flush=True
        )

        with serial.Serial(args.port, args.baud, timeout=0.01) as ser:
            time.sleep(0.12)
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except:
                pass

            # Safe initialization: keep motor disabled unless explicitly requested.
            init_cmds = [b"ST\r", b"MO=0\r", b"UM=5\r"]
            if args.enable_motor:
                init_cmds.append(b"MO=1\r")

            for cmd in init_cmds:
                ser.write(cmd)
                ser.flush()
                time.sleep(0.05)
                ser.read(ser.in_waiting or 256)

            print("[READY] Motor initialized, polling started", flush=True)

            # Start poller thread
            poller = threading.Thread(
                target=polling_worker, 
                args=(ser, state, output_bridge, args.mode), 
                daemon=True
            )
            poller.start()

            # Main loop: monitor and display status
            last_display = 0
            start_time = time.time()
            last_samples = 0
            while state.running:
                now = time.time()
                if now - last_display > 1.0:  # Status update every 1 second
                    steering_pct = int(state.last_steering * 100)
                    dt = max(1e-6, now - last_display) if last_display else 1.0
                    ds = state.sample_count - last_samples
                    inst_hz = ds / dt if last_display else 0.0
                    print(
                        f"[{state.sample_count:06d}] Steering: {steering_pct:+4d}% | "
                        f"Angle: {state.last_angle_16bit:5d} | Hz: {inst_hz:6.1f} | Errors: {state.error_count}",
                        flush=True
                    )
                    last_samples = state.sample_count
                    last_display = now
                time.sleep(0.05)

            # Shutdown
            print("\n[SHUTDOWN] Stopping...", flush=True)
            poller.join(timeout=1.0)
            
            ser.write(b"ST\r")
            ser.flush()
            time.sleep(0.02)
            ser.write(b"MO=0\r")
            ser.flush()
            
            output_bridge.close()
            
            elapsed = max(1e-6, time.time() - start_time)
            print(
                f"[DONE] {state.sample_count} samples | "
                f"{state.sample_count/elapsed:.1f} Hz | "
                f"Errors: {state.error_count}",
                flush=True
            )

    except serial.SerialException as e:
        print(f"[SERIAL ERROR] {e}", flush=True)
        return 1
    except Exception as e:
        print(f"[ERROR] {e}", flush=True)
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
