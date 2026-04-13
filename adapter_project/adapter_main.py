#!/usr/bin/env python3
"""Sim wheel adapter: Sim source -> Elmo torque command + optional vJoy axis output."""

from __future__ import annotations

import ctypes
import json
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
    "max_tc": 300,
    "max_tc_step_per_loop": 12,
    "elmo_command_mode": "tc",  # tc | pr
    "um_on_start": 1,
    "rm_on_start": 1,
    "max_pr_per_loop": 180,
    "max_pr_step_per_loop": 12,
    "ffb_input_max": 10000,
    "ffb_deadband": 50,
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

    def set_motor_on(self) -> None:
        self.send("MO=1")

    def set_motor_off(self) -> None:
        self.send("MO=0")

    def set_tc(self, tc: int) -> None:
        self.send(f"TC={tc}", wait=0.0)

    def set_um(self, um: int) -> None:
        self.send(f"UM={int(um)}")

    def set_rm(self, rm: int) -> None:
        self.send(f"RM={int(rm)}")

    def set_pr(self, pr: int) -> None:
        self.send(f"PR={int(pr)}", wait=0.0)

    def begin_motion(self) -> None:
        self.send("BG", wait=0.0)


class FfbSourceBase:
    @property
    def value(self) -> int:
        return 0

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
    """Receive DirectInput FFB constant-force packets from vJoy driver.

    Every AAA racing game sends DirectInput PT_CONSTREP packets to the vJoy
    virtual wheel device.  We register a native callback with FfbRegisterGenCB,
    which fires for every FFB packet.  Ffb_h_Packet gives us the raw HID bytes;
    we filter for type PT_CONSTREP (0x05) and decode the ±127-step magnitude.

    Compatible with: LFS, AC, ACC, iRacing, F1 2x/EA WRC, Dirt/GRID, Forza PC,
                     NFS Unbound, and any DirectInput FFB title on Windows.
    """

    _DLL_PATH   = r"C:\Program Files\vJoy\x64\vJoyInterface.dll"
    _PT_CONSTREP = 5   # HID force-feedback constant-force report type

    def __init__(self, device_id: int = 1, deadband: int = 50):
        self._dev    = max(1, int(device_id))
        self._dead   = max(0, int(deadband))
        self._value  = 0
        self._lock   = threading.Lock()
        self._running = False
        self._dll: Optional[ctypes.WinDLL] = None
        self._cb = None   # must keep reference alive — GC would free callback

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

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

        # Annotate used functions (cdecl, so plain CDLL works correctly)
        dll.FfbStart.restype           = ctypes.c_bool
        dll.FfbStart.argtypes          = [ctypes.c_uint]
        dll.FfbStop.argtypes           = [ctypes.c_uint]
        dll.FfbRegisterGenCB.argtypes  = [ctypes.c_void_p, ctypes.c_void_p]

        dll.Ffb_h_Type.restype  = ctypes.c_bool
        dll.Ffb_h_Type.argtypes = [ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_uint16)]

        dll.Ffb_h_Packet.restype  = ctypes.c_bool
        dll.Ffb_h_Packet.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
        ]

        CB_TYPE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
        self._cb = CB_TYPE(self._on_ffb)
        dll.FfbRegisterGenCB(self._cb, None)
        ok = dll.FfbStart(self._dev)
        self._running = True
        print(f"[vJOY-FFB] FfbStart(dev={self._dev}) ok={ok} — "
              "waiting for DirectInput constant-force packets …", flush=True)

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
            ptype   = ctypes.c_uint16(0)
            dsize   = ctypes.c_int(0)
            pdata   = ctypes.POINTER(ctypes.c_uint8)()

            ok = self._dll.Ffb_h_Packet(
                pEffect,
                ctypes.byref(ptype),
                ctypes.byref(dsize),
                ctypes.byref(pdata),
            )
            if not ok or ptype.value != self._PT_CONSTREP:
                return  # not a constant-force packet

            # Raw HID layout for PT_CONSTREP:
            #   byte[0] = report-id (0x05)
            #   byte[1] = bit7: direction (0=positive/1=negative); bits[6:0]: magnitude 0-127
            if dsize.value < 2 or not pdata:
                return

            b = pdata[1]
            negative  = bool(b >> 7)
            mag_raw   = b & 0x7F                       # 0-127
            force     = int((mag_raw / 127.0) * 10000) # scale to 0-10000
            if negative:
                force = -force
            if abs(force) <= self._dead:
                force = 0

            with self._lock:
                self._value = force

        except Exception:
            pass


@dataclass
class AdapterState:
    px: int = 0
    ffb_raw: int = 0
    cmd: int = 0


def ffb_to_tc(ffb_raw: int, max_tc: int, ffb_input_max: int) -> int:
    denom = max(1, int(ffb_input_max))
    scaled = int((ffb_raw / float(denom)) * max_tc)
    return max(-max_tc, min(max_tc, scaled))


def ffb_to_pr(ffb_raw: int, max_pr: int, ffb_input_max: int) -> int:
    denom = max(1, int(ffb_input_max))
    scaled = int((ffb_raw / float(denom)) * max_pr)
    return max(-max_pr, min(max_pr, scaled))


def px_to_vjoy_axis(px: int, max_pos_counts: int) -> int:
    clamped = max(-max_pos_counts, min(max_pos_counts, px))
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
    cmd_mode = str(cfg.get("elmo_command_mode", "tc")).lower().strip()

    with SingleInstance("Global\\Co2Root_AdapterProject"):
        elmo = ElmoClient(
            str(cfg["elmo_port"]),
            int(cfg["elmo_baud"]),
            float(cfg.get("serial_timeout_s", 0.008)),
        )
        src = build_source(cfg)
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

        if cfg.get("auto_motor_on", True):
            elmo.set_motor_on()
        if cmd_mode == "pr":
            elmo.set_pr(0)
        else:
            elmo.set_tc(0)

        state = AdapterState()
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
                        state.px = px_new
                        t_px_last_ok = time.perf_counter()
                    px_reads_since_log += 1

                state.ffb_raw = src.value
                if cmd_mode == "pr":
                    target = ffb_to_pr(
                        state.ffb_raw,
                        int(cfg.get("max_pr_per_loop", 180)),
                        int(cfg.get("ffb_input_max", 10000)),
                    )
                    state.cmd = slew_limit(state.cmd, target, int(cfg.get("max_pr_step_per_loop", 12)))
                    if state.cmd != 0:
                        elmo.set_pr(state.cmd)
                        elmo.begin_motion()
                else:
                    target = ffb_to_tc(state.ffb_raw, int(cfg["max_tc"]), int(cfg.get("ffb_input_max", 10000)))
                    state.cmd = slew_limit(state.cmd, target, int(cfg.get("max_tc_step_per_loop", 12)))
                    elmo.set_tc(state.cmd)

                if vjoy is not None:
                    try:
                        import pyvjoy

                        vjoy.set_axis(pyvjoy.HID_USAGE_X, px_to_vjoy_axis(state.px, max_pos_counts))
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
                        f"ADAPTER mode={cmd_mode:>2} pos={state.px:>10} ffb_raw={state.ffb_raw:>6} cmd={state.cmd:>5} "
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
                    elmo.set_pr(0)
                    elmo.begin_motion()
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
