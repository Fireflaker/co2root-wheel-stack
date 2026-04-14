#!/usr/bin/env python3
"""
Calibrate the true counts-per-revolution by measuring movement.
"""
from __future__ import annotations

import re
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


def main():
    port = serial.Serial("COM13", 115200, timeout=0.25)
    time.sleep(0.12)
    
    try:
        port.reset_input_buffer()
        port.reset_output_buffer()
    except:
        pass

    # Setup
    send(port, "ST", wait=0.04)
    send(port, "TC=0", wait=0.02)
    send(port, "MO=0", wait=0.04)
    send(port, "UM=5", wait=0.05)
    send(port, "RM=1", wait=0.05)
    send(port, "MO=1", wait=0.05)

    print("=== Counting rotations ===")
    
    # Test with different move sizes to find the pattern
    test_counts = [
        8192,      # 1/16 of 131072?
        16384,     # 1/8
        32768,     # 1/4
        65536,     # 1/2
        131072,    # assumed 1 full
    ]

    for test_count in test_counts:
        print(f"\nTest: PR={test_count}")
        
        px_before = query_int(port, "PX", wait=0.05)
        print(f"  PX before: {px_before}")
        
        send(port, f"PR={test_count}", wait=0.01)
        send(port, "BG", wait=0.01)
        
        time.sleep(5)  # Wait for movement
        
        px_after = query_int(port, "PX", wait=0.05)
        actual_delta = px_after - px_before if (px_after and px_before) else None
        
        print(f"  PX after: {px_after}")
        print(f"  Actual delta: {actual_delta}")
        
        if actual_delta:
            ratio = actual_delta / test_count
            print(f"  Ratio (actual/commanded): {ratio:.4f}")
            
            # Check if this matches a full revolution
            if abs(actual_delta) >= 130000:
                print(f"  ✓ This is ~1 full revolution!")
    
    # Shutdown
    send(port, "ST", wait=0.04)
    send(port, "TC=0", wait=0.02)
    send(port, "MO=0", wait=0.04)
    
    port.close()
    print("\nCalibration complete")


if __name__ == "__main__":
    main()
