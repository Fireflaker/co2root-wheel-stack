#!/usr/bin/env python3
from __future__ import annotations

import time
import pygame
import pyvjoy


pygame.init()
pygame.joystick.init()
js = pygame.joystick.Joystick(0)
js.init()
print(f"name={js.get_name()} axes={js.get_numaxes()}")

vj = pyvjoy.VJoyDevice(1)

for raw in [0, 4096, 8192, 12288, 16384, 20480, 24576, 28672, 32767]:
    vj.set_axis(pyvjoy.HID_USAGE_X, raw)
    time.sleep(0.2)
    pygame.event.pump()
    print(f"set={raw:5d} axis0={js.get_axis(0): .4f}")
