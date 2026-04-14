#!/usr/bin/env python3
"""Sim wheel adapter: Sim source -> Elmo torque command + optional vJoy axis output."""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import serial

from vjoy_state import load_input_state, pedal_to_vjoy_axis, released_pedal_vjoy_axis


ERROR_SUCCESS = 0

VJOY_FFB_PT_EFFREP = 0x01
VJOY_FFB_PT_CONDREP = 0x03
VJOY_FFB_PT_PRIDREP = 0x04
VJOY_FFB_PT_CONSTREP = 0x05
VJOY_FFB_PT_RAMPREP = 0x06
VJOY_FFB_PT_EFOPREP = 0x0A
VJOY_FFB_PT_CTRLREP = 0x0C

VJOY_FFB_CTRL_STOPALL = 3
VJOY_FFB_CTRL_DEVRST = 4
VJOY_FFB_CTRL_DEVPAUSE = 5
VJOY_FFB_CTRL_DEVCONT = 6

VJOY_FFB_OP_START = 1
VJOY_FFB_OP_SOLO = 2
VJOY_FFB_OP_STOP = 3

VJOY_FFB_EFFECT_NONE = 0
VJOY_FFB_EFFECT_CONST = 1
VJOY_FFB_EFFECT_RAMP = 2
VJOY_FFB_EFFECT_SQUARE = 3
VJOY_FFB_EFFECT_SINE = 4
VJOY_FFB_EFFECT_TRIANGLE = 5
VJOY_FFB_EFFECT_SAW_UP = 6
VJOY_FFB_EFFECT_SAW_DOWN = 7
VJOY_FFB_EFFECT_SPRING = 8
VJOY_FFB_EFFECT_DAMPER = 9
VJOY_FFB_EFFECT_INERTIA = 10
VJOY_FFB_EFFECT_FRICTION = 11


class VJoyFFBEffectReport(ctypes.Structure):
    _fields_ = [
        ("EffectBlockIndex", ctypes.c_ubyte),
        ("_reserved0", ctypes.c_ubyte * 3),
        ("EffectType", ctypes.c_uint32),
        ("Duration", ctypes.c_uint16),
        ("TrigerRpt", ctypes.c_uint16),
        ("SamplePrd", ctypes.c_uint16),
        ("Gain", ctypes.c_ubyte),
        ("TrigerBtn", ctypes.c_ubyte),
        ("Polar", ctypes.c_bool),
        ("_reserved1", ctypes.c_ubyte * 3),
        ("Direction", ctypes.c_ubyte),
        ("DirY", ctypes.c_ubyte),
    ]


class VJoyFFBEffectOp(ctypes.Structure):
    _fields_ = [
        ("EffectBlockIndex", ctypes.c_ubyte),
        ("_reserved0", ctypes.c_ubyte * 3),
        ("EffectOp", ctypes.c_uint32),
        ("LoopCount", ctypes.c_ubyte),
    ]


class VJoyFFBConstantEffect(ctypes.Structure):
    _fields_ = [
        ("EffectBlockIndex", ctypes.c_ubyte),
        ("_reserved", ctypes.c_ubyte * 3),
        ("Magnitude", ctypes.c_int16),
    ]


class VJoyFFBConditionEffect(ctypes.Structure):
    _fields_ = [
        ("EffectBlockIndex", ctypes.c_ubyte),
        ("_reserved0", ctypes.c_ubyte * 3),
        ("isY", ctypes.c_bool),
        ("_reserved1", ctypes.c_ubyte * 3),
        ("CenterPointOffset", ctypes.c_int16),
        ("_reserved2", ctypes.c_ubyte * 2),
        ("PosCoeff", ctypes.c_int16),
        ("_reserved3", ctypes.c_ubyte * 2),
        ("NegCoeff", ctypes.c_int16),
        ("_reserved4", ctypes.c_ubyte * 2),
        ("PosSatur", ctypes.c_uint32),
        ("NegSatur", ctypes.c_uint32),
        ("DeadBand", ctypes.c_int32),
    ]


class VJoyFFBPeriodicEffect(ctypes.Structure):
    _fields_ = [
        ("EffectBlockIndex", ctypes.c_ubyte),
        ("_reserved0", ctypes.c_ubyte * 3),
        ("Magnitude", ctypes.c_uint32),
        ("Offset", ctypes.c_int16),
        ("_reserved1", ctypes.c_ubyte * 2),
        ("Phase", ctypes.c_uint32),
        ("Period", ctypes.c_uint32),
    ]


class VJoyFFBRampEffect(ctypes.Structure):
    _fields_ = [
        ("EffectBlockIndex", ctypes.c_ubyte),
        ("_reserved0", ctypes.c_ubyte * 3),
        ("Start", ctypes.c_int16),
        ("_reserved1", ctypes.c_ubyte * 2),
        ("End", ctypes.c_int16),
    ]


DEFAULT_CONFIG = {
    "elmo_port": "COM13",
    "elmo_baud": 115200,
    "sim_source": "vjoy_ffb",  # serial | http | websocket | inject | vjoy_ffb
    "sim_serial_port": "COM11",
    "sim_serial_baud": 115200,
    "sim_http_url": "http://127.0.0.1:8888/api/GetGameData",
    "sim_ws_url": "ws://127.0.0.1:8888",
    "inject_sequence": [0, 5000, -5000, 5000, 0],
    "inject_hold_loops": 120,
    "loop_hz": 200,
    "motor_profile_name": "generic_test_servo",
    "motor_rated_voltage_v": 100.0,
    "motor_rated_current_a": 1.3,
    "max_tc": 300,
    "max_tc_step_per_loop": 12,
    "elmo_command_mode": "tc",  # tc | il | pr
    "um_on_start": 1,
    "rm_on_start": 1,
    "tc_probe_on_start": True,
    "tc_probe_value": 0,
    "require_true_torque": False,
    "fallback_to_pr_on_tc_reject": True,
    "pr_fallback_um": 5,
    "pr_fallback_rm": 1,
    "max_current_a": 2.0,
    "min_current_a": 0.05,
    "current_cmd_scale": 1000.0,
    "max_il_step_per_loop": 100,
    "max_pr_per_loop": 180,
    "max_pr_step_per_loop": 12,
    "release_motor_on_idle_ffb": False,
    "idle_release_after_s": 0.15,
    "ffb_input_max": 10000,
    "ffb_deadband": 50,
    "ffb_fallback_to_inject": True,
    "ffb_fallback_after_s": 1.5,
    "auto_motor_on": True,  # always enable motor on start
    "motor_off_on_exit": False,
    "enable_vjoy": True,
    "vjoy_device_id": 1,
    "max_position_counts": 0,
    "encoder_bits": 17,
    "wheel_lock_deg": 540.0,
    "status_log_every_s": 0.2,
    "px_poll_every_loops": 1,
    "serial_timeout_s": 0.008,
}


def parse_last_int(text: str) -> Optional[int]:
    nums = re.findall(r"-?\d+", text)
    if not nums:
        return None
    return int(nums[-1])


def response_indicates_elmo_error(text: str) -> bool:
    return "?;" in (text or "")


class SingleInstance:
    def __init__(self, name: str):
        self._name = name
        self._handle = None

    def __enter__(self):
        self._handle = ctypes.windll.kernel32.CreateMutexW(None, False, self._name)
        err = ctypes.windll.kernel32.GetLastError()
        if err == 183:  # ERROR_ALREADY_EXISTS
            raise RuntimeError(f"Adapter already running ({self._name})")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)


class ElmoClient:
    def __init__(self, port: str, baud: int, timeout_s: float = 0.008):
        self.port = port
        self.baud = baud
        self.timeout_s = timeout_s
        self.ser: Optional[serial.Serial] = None

    def open(self) -> None:
        self.ser = serial.Serial(self.port, self.baud, timeout=max(0.001, float(self.timeout_s)))
        time.sleep(0.05)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()

    def send(self, cmd: str, wait: float = 0.001) -> str:
        assert self.ser is not None
        self.ser.write((cmd + "\r").encode("ascii"))
        self.ser.flush()
        time.sleep(wait)
        raw = self.ser.read(self.ser.in_waiting or 128)
        return raw.decode("ascii", errors="replace").strip()

    def get_mo(self) -> Optional[int]:
        return parse_last_int(self.send("MO"))

    def get_px(self) -> Optional[int]:
        return parse_last_int(self.send("PX"))

    def get_ec(self) -> Optional[int]:
        return parse_last_int(self.send("EC"))

    def set_motor_on(self) -> str:
        return self.send("MO=1")

    def set_motor_off(self) -> str:
        return self.send("MO=0")

    def set_tc(self, tc: int) -> str:
        return self.send(f"TC={tc}", wait=0.0)

    def set_il(self, il: int) -> str:
        return self.send(f"IL={il}", wait=0.0)

    def set_um(self, um: int) -> str:
        return self.send(f"UM={int(um)}")

    def set_rm(self, rm: int) -> str:
        return self.send(f"RM={int(rm)}")

    def set_pr(self, pr: int) -> str:
        return self.send(f"PR={int(pr)}", wait=0.0)

    def begin_motion(self) -> str:
        return self.send("BG", wait=0.0)

    def stop_motion(self) -> str:
        return self.send("ST", wait=0.0)


def probe_tc_support(elmo: ElmoClient, probe_value: int) -> tuple[bool, str]:
    probe_resp = elmo.set_tc(int(probe_value))
    zero_resp = ""
    if int(probe_value) != 0:
        zero_resp = elmo.set_tc(0)
    ec = elmo.get_ec()
    responses = [resp for resp in (probe_resp, zero_resp) if resp]
    if any(response_indicates_elmo_error(resp) for resp in responses):
        return False, f"TC rejected responses={responses!r} ec={ec!r}"
    if ec not in (None, 0):
        return False, f"TC probe left nonzero EC={ec!r} responses={responses!r}"
    return True, f"TC probe accepted responses={responses!r} ec={ec!r}"


def resolve_runtime_command_mode(elmo: ElmoClient, cfg: dict, requested_mode: str) -> tuple[str, str]:
    mode = str(requested_mode).lower().strip()
    if mode == "il":
        return mode, "runtime mode=il"
    if mode != "tc":
        return mode, f"runtime mode={mode}"

    if not bool(cfg.get("tc_probe_on_start", True)):
        return mode, "runtime mode=tc (probe disabled)"

    ok, detail = probe_tc_support(elmo, int(cfg.get("tc_probe_value", 0)))
    if ok:
        return mode, detail

    if bool(cfg.get("require_true_torque", False)):
        raise RuntimeError(f"True torque required but TC probe failed: {detail}")

    if not bool(cfg.get("fallback_to_pr_on_tc_reject", True)):
        raise RuntimeError(f"TC probe failed and PR fallback is disabled: {detail}")

    elmo.set_um(int(cfg.get("pr_fallback_um", 5)))
    if cfg.get("pr_fallback_rm") is not None:
        elmo.set_rm(int(cfg.get("pr_fallback_rm", 1)))
    return "pr", f"TC unavailable; falling back to PR ({detail})"


class FfbSourceBase:
    @property
    def value(self) -> int:
        return 0

    def update_input_state(self, position_norm: float, velocity_norm: float) -> None:
        return

    def start(self) -> None:
        return

    def stop(self) -> None:
        return


class SerialFfbSource(FfbSourceBase):
    def __init__(self, port: str, baud: int, deadband: int):
        self._port = port
        self._baud = baud
        self._deadband = deadband
        self._value = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ser: Optional[serial.Serial] = None

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def start(self) -> None:
        self._ser = serial.Serial(self._port, self._baud, timeout=0.05)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ffb-serial")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()

    def _loop(self) -> None:
        buf = b""
        while self._running:
            try:
                chunk = self._ser.read(128)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("ascii", errors="ignore").strip()
                    try:
                        val = int(text)
                        if abs(val) <= self._deadband:
                            val = 0
                        with self._lock:
                            self._value = val
                    except ValueError:
                        pass
            except Exception:
                time.sleep(0.05)


class HttpFfbSource(FfbSourceBase):
    def __init__(self, url: str, deadband: int):
        self._url = url
        self._deadband = deadband
        self._value = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ffb-http")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        import urllib.request

        while self._running:
            try:
                req = urllib.request.Request(self._url, headers={"User-Agent": "adapter-project/1.0"})
                with urllib.request.urlopen(req, timeout=0.6) as r:
                    payload = json.loads(r.read().decode("utf-8", errors="replace"))
                val = self._extract(payload)
                if abs(val) <= self._deadband:
                    val = 0
                with self._lock:
                    self._value = val
            except Exception:
                time.sleep(0.03)
            time.sleep(0.02)

    def _extract(self, payload: object) -> int:
        keys = ("ffb", "force", "steeringforce", "finalforcefeedback", "torque")

        def walk(obj: object) -> Optional[int]:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    lk = str(k).lower()
                    if any(p in lk for p in keys) and isinstance(v, (int, float)):
                        return int(v)
                for v in obj.values():
                    found = walk(v)
                    if found is not None:
                        return found
            if isinstance(obj, list):
                for item in obj:
                    found = walk(item)
                    if found is not None:
                        return found
            return None

        return walk(payload) or 0


class WebSocketFfbSource(FfbSourceBase):
    def __init__(self, url: str, deadband: int):
        self._url = url
        self._deadband = deadband
        self._value = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ffb-websocket")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        import asyncio

        async def _run() -> None:
            try:
                import websockets
            except Exception:
                while self._running:
                    time.sleep(0.2)
                return

            while self._running:
                try:
                    async with websockets.connect(self._url, ping_interval=10, ping_timeout=10) as ws:
                        while self._running:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            val = self._extract(msg)
                            if val is None:
                                continue
                            if abs(val) <= self._deadband:
                                val = 0
                            with self._lock:
                                self._value = val
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    await asyncio.sleep(0.2)

        asyncio.run(_run())

    def _extract(self, msg: object) -> Optional[int]:
        if isinstance(msg, (bytes, bytearray)):
            try:
                msg = msg.decode("utf-8", errors="replace")
            except Exception:
                return None

        if isinstance(msg, str):
            msg = msg.strip()
            iv = parse_last_int(msg)
            if iv is not None:
                return iv
            try:
                obj = json.loads(msg)
            except Exception:
                return None
            return HttpFfbSource("", self._deadband)._extract(obj)

        if isinstance(msg, (dict, list)):
            return HttpFfbSource("", self._deadband)._extract(msg)

        return None


class InjectFfbSource(FfbSourceBase):
    def __init__(self, seq: list[int], hold_loops: int):
        self._seq = seq if seq else [0]
        self._hold = max(1, int(hold_loops))
        self._idx = 0
        self._count = self._hold

    @property
    def value(self) -> int:
        v = self._seq[self._idx]
        self._count -= 1
        if self._count <= 0:
            self._idx = (self._idx + 1) % len(self._seq)
            self._count = self._hold
        return v


class VJoyFfbSource(FfbSourceBase):
    """Receive DirectInput FFB packets from vJoy driver.

    This is the direct game-to-adapter path. Games write DirectInput FFB to the
    vJoy wheel device, and the adapter consumes those packets via vJoy's native
    callback helpers without going through SimHub.

    Compatible with: LFS, AC, ACC, iRacing, F1 2x/EA WRC, Dirt/GRID, Forza PC,
                     NFS Unbound, and any DirectInput FFB title on Windows.
    """

    _DLL_PATH = r"C:\Program Files\vJoy\x64\vJoyInterface.dll"

    def __init__(self, device_id: int = 1, deadband: int = 50):
        self._dev = max(1, int(device_id))
        self._dead = max(0, int(deadband))
        self._base_value = 0
        self._device_gain = 255
        self._effect_gain = 255
        self._effect_type = VJOY_FFB_EFFECT_NONE
        self._effect_duration_ms = 0xFFFF
        self._effect_start_t = 0.0
        self._effect_running = True
        self._condition: Optional[VJoyFFBConditionEffect] = None
        self._position_norm = 0.0
        self._velocity_norm = 0.0
        self._periodic: Optional[VJoyFFBPeriodicEffect] = None
        self._ramp: Optional[VJoyFFBRampEffect] = None
        self._lock = threading.Lock()
        self._running = False
        self._dll: Optional[ctypes.WinDLL] = None
        self._cb = None   # must keep reference alive — GC would free callback
        self._last_packet_t = 0.0
        self._last_packet_type: Optional[int] = None
        self._last_effect_type: Optional[int] = None

    @property
    def value(self) -> int:
        with self._lock:
            force = self._compute_force_locked(time.perf_counter())
            if abs(force) <= self._dead:
                return 0
            return force

    def update_input_state(self, position_norm: float, velocity_norm: float) -> None:
        with self._lock:
            self._position_norm = max(-1.0, min(1.0, float(position_norm)))
            self._velocity_norm = max(-1.0, min(1.0, float(velocity_norm)))

    def start(self) -> None:
        # Use pyvjoy's own cdecl DLL instance — same LoadLibrary call that already
        # owns the vJoy acquire handle, so FfbStart succeeds without a second
        # AcquireVJD that would conflict.
        try:
            import pyvjoy._sdk as _ps
            dll = _ps._vj
        except Exception:
            import ctypes as _ct
            # Fallback: cdecl (not WinDLL) — vJoy exports are __cdecl
            dll = _ct.cdll.LoadLibrary(self._DLL_PATH)

        self._dll = dll

        # vJoy helper APIs return Win32 status codes. ERROR_SUCCESS is 0, so the
        # restype must stay integer-based rather than bool or the success path is lost.
        dll.FfbStart.restype           = ctypes.c_bool
        dll.FfbStart.argtypes          = [ctypes.c_uint]
        dll.FfbStop.argtypes           = [ctypes.c_uint]
        dll.FfbRegisterGenCB.argtypes  = [ctypes.c_void_p, ctypes.c_void_p]

        dll.Ffb_h_Type.restype  = ctypes.c_uint32
        dll.Ffb_h_Type.argtypes = [ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_uint16)]

        dll.Ffb_h_Packet.restype  = ctypes.c_uint32
        dll.Ffb_h_Packet.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
        ]

        dll.Ffb_h_Eff_Constant.restype = ctypes.c_uint32
        dll.Ffb_h_Eff_Constant.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(VJoyFFBConstantEffect),
        ]

        dll.Ffb_h_Eff_Report.restype = ctypes.c_uint32
        dll.Ffb_h_Eff_Report.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(VJoyFFBEffectReport),
        ]

        dll.Ffb_h_EffOp.restype = ctypes.c_uint32
        dll.Ffb_h_EffOp.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(VJoyFFBEffectOp),
        ]

        dll.Ffb_h_Eff_Cond.restype = ctypes.c_uint32
        dll.Ffb_h_Eff_Cond.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(VJoyFFBConditionEffect),
        ]

        dll.Ffb_h_Eff_Period.restype = ctypes.c_uint32
        dll.Ffb_h_Eff_Period.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(VJoyFFBPeriodicEffect),
        ]

        dll.Ffb_h_Eff_Ramp.restype = ctypes.c_uint32
        dll.Ffb_h_Eff_Ramp.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(VJoyFFBRampEffect),
        ]

        dll.Ffb_h_DevGain.restype = ctypes.c_uint32
        dll.Ffb_h_DevGain.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
        ]

        dll.Ffb_h_DevCtrl.restype = ctypes.c_uint32
        dll.Ffb_h_DevCtrl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]

        CB_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
        self._cb = CB_TYPE(self._on_ffb)
        dll.FfbRegisterGenCB(self._cb, None)
        ok = dll.FfbStart(self._dev)
        self._running = True
        print(
            f"[vJOY-FFB] FfbStart(dev={self._dev}) ok={ok} — "
            "waiting for direct game FFB packets (SimHub not required) …",
            flush=True,
        )

    def stop(self) -> None:
        self._running = False
        if self._dll:
            try:
                self._dll.FfbStop(self._dev)
            except Exception:
                pass

    def _on_ffb(self, pEffect: int, _: int) -> None:
        """Native FFB callback — runs on the vJoy driver thread."""
        if not self._running or not pEffect:
            return
        try:
            packet_type = ctypes.c_uint16(0)
            if self._dll.Ffb_h_Type(pEffect, ctypes.byref(packet_type)) != ERROR_SUCCESS:
                return

            gain = ctypes.c_ubyte(self._device_gain)
            if self._dll.Ffb_h_DevGain(pEffect, ctypes.byref(gain)) == ERROR_SUCCESS:
                self._device_gain = int(gain.value)

            with self._lock:
                now = time.perf_counter()
                self._handle_packet_locked(int(packet_type.value), pEffect, now)
                self._last_packet_t = now

        except Exception:
            pass

    def _handle_packet_locked(self, packet_type: int, packet_ptr: int, now: float) -> None:
        self._maybe_log_packet_transition(packet_type)

        if packet_type == VJOY_FFB_PT_EFFREP:
            report = VJoyFFBEffectReport()
            if self._dll.Ffb_h_Eff_Report(packet_ptr, ctypes.byref(report)) == ERROR_SUCCESS:
                new_effect_type = int(report.EffectType)
                if new_effect_type != self._effect_type:
                    self._base_value = 0
                    self._periodic = None
                    self._ramp = None
                    self._condition = None
                self._effect_type = new_effect_type
                self._effect_gain = int(report.Gain)
                self._effect_duration_ms = int(report.Duration)
                self._effect_start_t = now
                self._effect_running = True
                self._maybe_log_effect_transition(self._effect_type)
            return

        if packet_type == VJOY_FFB_PT_EFOPREP:
            operation = VJoyFFBEffectOp()
            if self._dll.Ffb_h_EffOp(packet_ptr, ctypes.byref(operation)) == ERROR_SUCCESS:
                if int(operation.EffectOp) == VJOY_FFB_OP_STOP:
                    self._effect_running = False
                elif int(operation.EffectOp) in (VJOY_FFB_OP_START, VJOY_FFB_OP_SOLO):
                    self._effect_running = True
                    self._effect_start_t = now
            return

        if packet_type == VJOY_FFB_PT_CONSTREP:
            effect = VJoyFFBConstantEffect()
            if self._dll.Ffb_h_Eff_Constant(packet_ptr, ctypes.byref(effect)) == ERROR_SUCCESS:
                self._effect_type = VJOY_FFB_EFFECT_CONST
                self._base_value = int(effect.Magnitude)
                self._periodic = None
                self._ramp = None
                self._effect_start_t = now
            return

        if packet_type == VJOY_FFB_PT_RAMPREP:
            ramp = VJoyFFBRampEffect()
            if self._dll.Ffb_h_Eff_Ramp(packet_ptr, ctypes.byref(ramp)) == ERROR_SUCCESS:
                self._effect_type = VJOY_FFB_EFFECT_RAMP
                self._ramp = ramp
                self._periodic = None
                self._effect_start_t = now
            return

        if packet_type == VJOY_FFB_PT_PRIDREP:
            periodic = VJoyFFBPeriodicEffect()
            if self._dll.Ffb_h_Eff_Period(packet_ptr, ctypes.byref(periodic)) == ERROR_SUCCESS:
                if self._effect_type == VJOY_FFB_EFFECT_NONE:
                    self._effect_type = VJOY_FFB_EFFECT_SINE
                self._periodic = periodic
                self._ramp = None
                self._effect_start_t = now
            return

        if packet_type == VJOY_FFB_PT_CONDREP:
            condition = VJoyFFBConditionEffect()
            if self._dll.Ffb_h_Eff_Cond(packet_ptr, ctypes.byref(condition)) == ERROR_SUCCESS and not bool(condition.isY):
                self._condition = condition
                self._effect_start_t = now
            return

        if packet_type == VJOY_FFB_PT_CTRLREP:
            control = ctypes.c_uint32(0)
            if self._dll.Ffb_h_DevCtrl(packet_ptr, ctypes.byref(control)) == ERROR_SUCCESS:
                if int(control.value) in (VJOY_FFB_CTRL_STOPALL, VJOY_FFB_CTRL_DEVRST, VJOY_FFB_CTRL_DEVPAUSE):
                    self._effect_running = False
                elif int(control.value) == VJOY_FFB_CTRL_DEVCONT:
                    self._effect_running = True
                    self._effect_start_t = now
            return

    def _maybe_log_packet_transition(self, packet_type: int) -> None:
        if packet_type == self._last_packet_type:
            return
        self._last_packet_type = packet_type
        print(f"[vJOY-FFB] packet type={packet_type}", flush=True)

    def _maybe_log_effect_transition(self, effect_type: int) -> None:
        if effect_type == self._last_effect_type:
            return
        self._last_effect_type = effect_type
        print(f"[vJOY-FFB] effect type={effect_type}", flush=True)

    def _compute_force_locked(self, now: float) -> int:
        if not self._effect_running:
            return 0
        if self._effect_duration_ms not in (0, 0xFFFF):
            if (now - self._effect_start_t) * 1000.0 >= self._effect_duration_ms:
                return 0

        if self._effect_type == VJOY_FFB_EFFECT_CONST:
            raw = self._base_value
        elif self._effect_type == VJOY_FFB_EFFECT_RAMP and self._ramp is not None:
            raw = vjoy_ramp_to_ffb_raw(
                self._ramp.Start,
                self._ramp.End,
                now - self._effect_start_t,
                self._effect_duration_ms,
            )
        elif self._effect_type in (
            VJOY_FFB_EFFECT_SQUARE,
            VJOY_FFB_EFFECT_SINE,
            VJOY_FFB_EFFECT_TRIANGLE,
            VJOY_FFB_EFFECT_SAW_UP,
            VJOY_FFB_EFFECT_SAW_DOWN,
        ) and self._periodic is not None:
            raw = vjoy_periodic_to_ffb_raw(
                int(self._periodic.Magnitude),
                int(self._periodic.Offset),
                int(self._periodic.Phase),
                now - self._effect_start_t,
                int(self._periodic.Period),
                self._effect_type,
            )
        elif self._effect_type in (
            VJOY_FFB_EFFECT_SPRING,
            VJOY_FFB_EFFECT_DAMPER,
            VJOY_FFB_EFFECT_INERTIA,
            VJOY_FFB_EFFECT_FRICTION,
        ) and self._condition is not None:
            raw = vjoy_condition_to_ffb_raw(
                self._effect_type,
                int(self._condition.CenterPointOffset),
                int(self._condition.PosCoeff),
                int(self._condition.NegCoeff),
                int(self._condition.PosSatur),
                int(self._condition.NegSatur),
                int(self._condition.DeadBand),
                self._position_norm,
                self._velocity_norm,
            )
        else:
            raw = self._base_value

        return vjoy_scale_with_gains(raw, self._effect_gain, self._device_gain)

    def packet_age_s(self) -> float:
        if self._last_packet_t <= 0.0:
            return 1e9
        return max(0.0, time.perf_counter() - self._last_packet_t)


@dataclass
class AdapterState:
    px: int = 0
    px_center: int = 0
    velocity_counts_per_s: float = 0.0
    ffb_raw: int = 0
    cmd: int = 0


def vjoy_constant_magnitude_to_ffb_raw(magnitude: int, device_gain: int = 255) -> int:
    clamped_magnitude = max(-10000, min(10000, int(magnitude)))
    clamped_gain = max(0, min(255, int(device_gain)))
    if clamped_magnitude == 0 or clamped_gain == 0:
        return 0
    return int(round(clamped_magnitude * (clamped_gain / 255.0)))


def vjoy_scale_with_gains(raw_force: int, effect_gain: int = 255, device_gain: int = 255) -> int:
    force = max(-10000, min(10000, int(raw_force)))
    if force == 0:
        return 0
    eff = max(0, min(255, int(effect_gain))) / 255.0
    dev = max(0, min(255, int(device_gain))) / 255.0
    scaled = int(round(force * eff * dev))
    return max(-10000, min(10000, scaled))


def _wave_phase(elapsed_s: float, period_ms: int, phase: int) -> float:
    if period_ms <= 0:
        return 0.0
    return ((elapsed_s / (period_ms / 1000.0)) + (phase / 255.0)) % 1.0


def vjoy_periodic_to_ffb_raw(
    magnitude: int,
    offset: int,
    phase: int,
    elapsed_s: float,
    period_ms: int,
    effect_type: int,
) -> int:
    mag = max(0, min(10000, int(magnitude)))
    ofs = max(-10000, min(10000, int(offset)))
    phase_norm = _wave_phase(max(0.0, float(elapsed_s)), int(period_ms), int(phase))

    if effect_type == VJOY_FFB_EFFECT_SQUARE:
        wave = 1.0 if phase_norm < 0.5 else -1.0
    elif effect_type == VJOY_FFB_EFFECT_TRIANGLE:
        wave = 1.0 - 4.0 * abs(phase_norm - 0.5)
    elif effect_type == VJOY_FFB_EFFECT_SAW_UP:
        wave = (2.0 * phase_norm) - 1.0
    elif effect_type == VJOY_FFB_EFFECT_SAW_DOWN:
        wave = 1.0 - (2.0 * phase_norm)
    else:
        wave = math.sin(2.0 * math.pi * phase_norm)

    return max(-10000, min(10000, int(round(ofs + (mag * wave)))))


def vjoy_ramp_to_ffb_raw(start: int, end: int, elapsed_s: float, duration_ms: int) -> int:
    start_i = max(-10000, min(10000, int(start)))
    end_i = max(-10000, min(10000, int(end)))
    if duration_ms in (0, 0xFFFF):
        return end_i
    progress = max(0.0, min(1.0, (float(elapsed_s) * 1000.0) / float(duration_ms)))
    return int(round(start_i + ((end_i - start_i) * progress)))


def _normalize_vjoy_condition_limit(value: int) -> int:
    limited = max(0, int(value))
    if limited > 10000:
        return 10000
    if limited <= 255:
        return int(round((limited / 255.0) * 10000.0))
    return limited


def vjoy_condition_to_ffb_raw(
    effect_type: int,
    center_point_offset: int,
    pos_coeff: int,
    neg_coeff: int,
    pos_saturation: int,
    neg_saturation: int,
    deadband: int,
    position_norm: float,
    velocity_norm: float,
) -> int:
    pos_term = max(-1.0, min(1.0, float(position_norm))) * 10000.0
    vel_term = max(-1.0, min(1.0, float(velocity_norm))) * 10000.0
    center = max(-10000, min(10000, int(center_point_offset)))
    band = max(0, min(10000, abs(int(deadband))))

    if effect_type == VJOY_FFB_EFFECT_SPRING:
        signal = pos_term - center
        proportional = True
    elif effect_type in (VJOY_FFB_EFFECT_DAMPER, VJOY_FFB_EFFECT_INERTIA):
        signal = vel_term
        proportional = True
    elif effect_type == VJOY_FFB_EFFECT_FRICTION:
        signal = vel_term
        proportional = False
    else:
        return 0

    if abs(signal) <= band:
        return 0

    signal_sign = 1.0 if signal >= 0.0 else -1.0
    coeff = int(pos_coeff) if signal >= 0.0 else int(neg_coeff)
    saturation = _normalize_vjoy_condition_limit(pos_saturation if signal >= 0.0 else neg_saturation)

    if proportional:
        force = -signal * (coeff / 10000.0)
    else:
        force = -signal_sign * abs(coeff)

    limited = max(-float(saturation), min(float(saturation), force))
    return max(-10000, min(10000, int(round(limited))))


def ffb_to_tc(ffb_raw: int, max_tc: int, ffb_input_max: int) -> int:
    denom = max(1, int(ffb_input_max))
    scaled = int((ffb_raw / float(denom)) * max_tc)
    return max(-max_tc, min(max_tc, scaled))


def ffb_to_pr(ffb_raw: int, max_pr: int, ffb_input_max: int) -> int:
    denom = max(1, int(ffb_input_max))
    scaled = int((ffb_raw / float(denom)) * max_pr)
    return max(-max_pr, min(max_pr, scaled))


def current_a_to_il_counts(current_a: float, current_cmd_scale: float) -> int:
    return int(round(float(current_a) * float(current_cmd_scale)))


def scale_ffb_signal(ffb_raw: int, ffb_strength: float, ffb_input_max: int) -> int:
    denom = max(1, int(ffb_input_max))
    strength = max(0.0, float(ffb_strength))
    scaled = int(round(ffb_raw * strength))
    return max(-denom, min(denom, scaled))


def resolve_max_current_a(cfg: dict) -> float:
    explicit = float(cfg.get("max_current_a", 0.0) or 0.0)
    if explicit > 0.0:
        return explicit

    rated = max(0.0, float(cfg.get("motor_rated_current_a", 0.0) or 0.0))
    utilization = max(0.0, min(1.0, float(cfg.get("motor_current_utilization", 0.5) or 0.5)))
    if rated <= 0.0:
        return 0.0
    return rated * utilization


def ffb_to_il(
    ffb_raw: int,
    max_current_a: float,
    min_current_a: float,
    ffb_input_max: int,
    current_cmd_scale: float,
) -> int:
    denom = max(1, int(ffb_input_max))
    norm = max(-1.0, min(1.0, ffb_raw / float(denom)))
    if norm == 0.0:
        return 0

    max_current = max(0.0, float(max_current_a))
    min_current = max(0.0, float(min_current_a))
    if max_current <= 0.0:
        return 0

    target_current = abs(norm) * max_current
    if target_current < min_current:
        target_current = min_current

    cmd = current_a_to_il_counts(target_current, current_cmd_scale)
    return -cmd if norm < 0.0 else cmd


def px_to_vjoy_axis(px: int, max_pos_counts: int, px_center: int = 0) -> int:
    relative_px = int(px) - int(px_center)
    clamped = max(-max_pos_counts, min(max_pos_counts, relative_px))
    norm = clamped / max_pos_counts
    return int((norm + 1.0) * 16383) + 1


def resolve_max_position_counts(cfg: dict) -> int:
    explicit = int(cfg.get("max_position_counts", 0) or 0)
    if explicit > 0:
        return explicit

    bits = int(cfg.get("encoder_bits", 17))
    lock_deg = float(cfg.get("wheel_lock_deg", 540.0))
    counts_per_rev = float(2 ** bits)
    return max(1, int(counts_per_rev * (lock_deg / 360.0)))


def slew_limit(current: int, target: int, step_limit: int) -> int:
    limit = max(1, int(step_limit))
    delta = target - current
    if delta > limit:
        return current + limit
    if delta < -limit:
        return current - limit
    return target


def load_config(path: Path) -> dict:
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="ascii")
        return dict(DEFAULT_CONFIG)
    data = json.loads(path.read_text(encoding="utf-8"))
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def build_source(cfg: dict) -> FfbSourceBase:
    mode = str(cfg["sim_source"]).lower()
    if mode == "serial":
        return SerialFfbSource(cfg["sim_serial_port"], int(cfg["sim_serial_baud"]), int(cfg["ffb_deadband"]))
    if mode == "http":
        return HttpFfbSource(cfg["sim_http_url"], int(cfg["ffb_deadband"]))
    if mode == "websocket":
        return WebSocketFfbSource(cfg["sim_ws_url"], int(cfg["ffb_deadband"]))
    if mode == "vjoy_ffb":
        return VJoyFfbSource(int(cfg.get("vjoy_device_id", 1)), int(cfg["ffb_deadband"]))
    return InjectFfbSource([int(x) for x in cfg["inject_sequence"]], int(cfg["inject_hold_loops"]))


def try_init_vjoy(cfg: dict):
    if not cfg.get("enable_vjoy", True):
        return None
    try:
        import pyvjoy

        return pyvjoy.VJoyDevice(int(cfg["vjoy_device_id"]))
    except Exception:
        return None


def main() -> int:
    root = Path(__file__).resolve().parent
    cfg = load_config(root / "config.json")
    loop_dt = 1.0 / float(cfg["loop_hz"])
    status_log_every_s = max(0.05, float(cfg.get("status_log_every_s", 1.0)))
    px_poll_every_loops = max(1, int(cfg.get("px_poll_every_loops", 1)))
    max_pos_counts = resolve_max_position_counts(cfg)
    max_current_a = resolve_max_current_a(cfg)
    cmd_mode = str(cfg.get("elmo_command_mode", "tc")).lower().strip()
    sim_mode = str(cfg.get("sim_source", "inject")).lower().strip()

    with SingleInstance("Global\\Co2Root_AdapterProject"):
        elmo = ElmoClient(
            str(cfg["elmo_port"]),
            int(cfg["elmo_baud"]),
            float(cfg.get("serial_timeout_s", 0.008)),
        )
        src = build_source(cfg)
        fallback_src: Optional[InjectFfbSource] = None
        if sim_mode == "vjoy_ffb" and bool(cfg.get("ffb_fallback_to_inject", True)):
            fallback_src = InjectFfbSource(
                [int(x) for x in cfg.get("inject_sequence", [0, 150, -150, 0])],
                int(cfg.get("inject_hold_loops", 60)),
            )
        fallback_after_s = max(0.2, float(cfg.get("ffb_fallback_after_s", 1.5)))
        vjoy = try_init_vjoy(cfg)

        stop_evt = threading.Event()

        def _stop(*_):
            stop_evt.set()

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        elmo.open()
        src.start()

        if cfg.get("um_on_start") is not None:
            elmo.set_um(int(cfg.get("um_on_start", 1)))
        if cfg.get("rm_on_start") is not None:
            elmo.set_rm(int(cfg.get("rm_on_start", 1)))

        cmd_mode, mode_detail = resolve_runtime_command_mode(elmo, cfg, cmd_mode)
        print(f"ADAPTER mode-select {mode_detail}", flush=True)

        if cfg.get("auto_motor_on", True):
            elmo.set_motor_on()
        motor_enabled = bool(cfg.get("auto_motor_on", True))
        if cmd_mode == "pr":
            elmo.set_pr(0)
        elif cmd_mode == "il":
            elmo.set_il(0)
        else:
            elmo.set_tc(0)

        state = AdapterState()
        px0 = elmo.get_px()
        if px0 is not None:
            state.px = px0
            state.px_center = px0
        last_px_sample = state.px
        last_px_sample_t = time.perf_counter()
        print(
            "ADAPTER wheel-map "
            f"center_px={state.px_center} "
            f"max_counts={max_pos_counts} "
            f"wheel_lock_deg={cfg.get('wheel_lock_deg', 540.0)} "
            f"resolved_max_current_a={max_current_a:.3f} "
            f"idle_release={bool(cfg.get('release_motor_on_idle_ffb', False))}",
            flush=True,
        )
        idle_release_enabled = bool(cfg.get("release_motor_on_idle_ffb", False))
        idle_release_after_s = max(0.0, float(cfg.get("idle_release_after_s", 0.15)))
        idle_since = time.perf_counter()
        t_last_log = 0.0
        loop_count = 0
        loop_overrun_count = 0
        t_px_last_ok = time.perf_counter()
        px_reads_since_log = 0
        px_rate_window_start = t_px_last_ok

        try:
            while not stop_evt.is_set():
                t0 = time.perf_counter()
                px_read_ms = 0.0
                loop_count += 1

                if loop_count % px_poll_every_loops == 0:
                    t_px0 = time.perf_counter()
                    px_new = elmo.get_px()
                    px_read_ms = (time.perf_counter() - t_px0) * 1000.0
                    if px_new is not None:
                        now_px = time.perf_counter()
                        dt_px = max(1e-6, now_px - last_px_sample_t)
                        state.velocity_counts_per_s = (px_new - last_px_sample) / dt_px
                        last_px_sample = px_new
                        last_px_sample_t = now_px
                        state.px = px_new
                        t_px_last_ok = now_px
                    px_reads_since_log += 1

                src.update_input_state(
                    (state.px - state.px_center) / float(max_pos_counts),
                    state.velocity_counts_per_s / float(max_pos_counts),
                )

                state.ffb_raw = src.value
                if (
                    fallback_src is not None
                    and isinstance(src, VJoyFfbSource)
                    and src.packet_age_s() >= fallback_after_s
                    and abs(state.ffb_raw) <= int(cfg.get("ffb_deadband", 50))
                ):
                    state.ffb_raw = fallback_src.value
                effective_ffb = scale_ffb_signal(
                    state.ffb_raw,
                    float(cfg.get("ffb_strength", 1.0)),
                    int(cfg.get("ffb_input_max", 10000)),
                )

                if effective_ffb == 0:
                    if idle_since <= 0.0:
                        idle_since = time.perf_counter()
                    if idle_release_enabled and motor_enabled and (time.perf_counter() - idle_since) >= idle_release_after_s:
                        if cmd_mode == "pr":
                            elmo.stop_motion()
                            elmo.set_pr(0)
                        elif cmd_mode == "il":
                            elmo.set_il(0)
                        else:
                            elmo.set_tc(0)
                        elmo.set_motor_off()
                        motor_enabled = False
                        state.cmd = 0
                else:
                    idle_since = 0.0
                    if not motor_enabled and cfg.get("auto_motor_on", True):
                        elmo.set_motor_on()
                        motor_enabled = True

                if not motor_enabled:
                    now = time.perf_counter()
                    if now - t_last_log >= status_log_every_s:
                        window_s = max(1e-6, now - px_rate_window_start)
                        px_hz = px_reads_since_log / window_s
                        px_age_ms = (now - t_px_last_ok) * 1000.0
                        loop_ms = (now - t0) * 1000.0
                        overrun_pct = (100.0 * loop_overrun_count / loop_count) if loop_count else 0.0
                        print(
                            f"ADAPTER mode={cmd_mode:>2} profile={cfg.get('motor_profile_name', 'unknown')} pos={state.px:>10} rel={state.px - state.px_center:>10} "
                            f"ffb_raw={state.ffb_raw:>6} eff={effective_ffb:>6} cmd={state.cmd:>5} motor=off "
                            f"loop_ms={loop_ms:>6.2f} px_ms={px_read_ms:>6.2f} px_hz={px_hz:>6.1f} "
                            f"px_age_ms={px_age_ms:>7.1f} overrun={overrun_pct:>5.1f}%",
                            flush=True,
                        )
                        t_last_log = now
                        px_reads_since_log = 0
                        px_rate_window_start = now

                    sleep_for = loop_dt - (time.perf_counter() - t0)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    else:
                        loop_overrun_count += 1
                    continue

                if cmd_mode == "pr":
                    target = ffb_to_pr(
                        effective_ffb,
                        int(cfg.get("max_pr_per_loop", 180)),
                        int(cfg.get("ffb_input_max", 10000)),
                    )
                    state.cmd = slew_limit(state.cmd, target, int(cfg.get("max_pr_step_per_loop", 12)))
                    if state.cmd != 0:
                        elmo.set_pr(state.cmd)
                        elmo.begin_motion()
                elif cmd_mode == "il":
                    target = ffb_to_il(
                        effective_ffb,
                        max_current_a,
                        float(cfg.get("min_current_a", 0.05)),
                        int(cfg.get("ffb_input_max", 10000)),
                        float(cfg.get("current_cmd_scale", 1000.0)),
                    )
                    state.cmd = slew_limit(
                        state.cmd,
                        target,
                        int(cfg.get("max_il_step_per_loop", 100)),
                    )
                    elmo.set_il(state.cmd)
                else:
                    target = ffb_to_tc(effective_ffb, int(cfg["max_tc"]), int(cfg.get("ffb_input_max", 10000)))
                    state.cmd = slew_limit(state.cmd, target, int(cfg.get("max_tc_step_per_loop", 12)))
                    elmo.set_tc(state.cmd)

                if vjoy is not None:
                    try:
                        import pyvjoy

                        vjoy.set_axis(pyvjoy.HID_USAGE_X, px_to_vjoy_axis(state.px, max_pos_counts, state.px_center))
                        pedal_state = load_input_state()
                        vjoy.set_axis(pyvjoy.HID_USAGE_Z, pedal_to_vjoy_axis(pedal_state["throttle"]))
                        vjoy.set_axis(pyvjoy.HID_USAGE_RZ, pedal_to_vjoy_axis(pedal_state["brake"]))
                        vjoy.set_axis(pyvjoy.HID_USAGE_SL0, released_pedal_vjoy_axis())
                        vjoy.set_axis(pyvjoy.HID_USAGE_SL1, released_pedal_vjoy_axis())
                    except Exception:
                        pass

                now = time.perf_counter()
                if now - t_last_log >= status_log_every_s:
                    window_s = max(1e-6, now - px_rate_window_start)
                    px_hz = px_reads_since_log / window_s
                    px_age_ms = (now - t_px_last_ok) * 1000.0
                    loop_ms = (now - t0) * 1000.0
                    overrun_pct = (100.0 * loop_overrun_count / loop_count) if loop_count else 0.0
                    print(
                        f"ADAPTER mode={cmd_mode:>2} profile={cfg.get('motor_profile_name', 'unknown')} pos={state.px:>10} rel={state.px - state.px_center:>10} "
                        f"ffb_raw={state.ffb_raw:>6} eff={effective_ffb:>6} cmd={state.cmd:>5} "
                        f"loop_ms={loop_ms:>6.2f} px_ms={px_read_ms:>6.2f} px_hz={px_hz:>6.1f} "
                        f"px_age_ms={px_age_ms:>7.1f} overrun={overrun_pct:>5.1f}%",
                        flush=True,
                    )
                    t_last_log = now
                    px_reads_since_log = 0
                    px_rate_window_start = now

                sleep_for = loop_dt - (time.perf_counter() - t0)
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    loop_overrun_count += 1
        finally:
            try:
                if cmd_mode == "pr":
                    elmo.stop_motion()
                    elmo.set_pr(0)
                    elmo.begin_motion()
                elif cmd_mode == "il":
                    elmo.set_il(0)
                else:
                    elmo.set_tc(0)
                if cfg.get("motor_off_on_exit", False):
                    elmo.set_motor_off()
            except Exception:
                pass
            src.stop()
            elmo.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
