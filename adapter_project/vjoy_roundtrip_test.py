#!/usr/bin/env python3
from __future__ import annotations

import time
import pygame
import pyvjoy


def main() -> int:
    pygame.init()
    pygame.joystick.init()

    count = pygame.joystick.get_count()
    print(f"joystick_count={count}")
    devices = []
    for i in range(count):
        js = pygame.joystick.Joystick(i)
        js.init()
        name = js.get_name()
        axes = js.get_numaxes()
        print(f"idx={i} name={name!r} axes={axes}")
        devices.append(js)

    try:
        vj = pyvjoy.VJoyDevice(1)
    except Exception as e:
        print(f"vjoy_open_failed: {e}")
        return 1

    # Sweep X axis: left, center, right, center
    sequence = [0, 16384, 32767, 16384]
    print("sweeping_vjoy_x...")
    for raw in sequence:
        vj.set_axis(pyvjoy.HID_USAGE_X, raw)
        pygame.event.pump()
        sample = []
        for js in devices:
            if js.get_numaxes() > 0:
                sample.append((js.get_name(), round(js.get_axis(0), 4)))
        print(f"set={raw} samples={sample}")
        time.sleep(0.35)

    print("test_done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
