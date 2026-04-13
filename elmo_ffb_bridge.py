#!/usr/bin/env python3
"""
elmo_ffb_bridge.py
==================
Real-time bridge between an Elmo Gold servo drive and Windows gaming.

- Polls encoder position from Elmo → updates vJoy X axis (steering angle)
- Receives FFB force values from SimHub via virtual serial pair → sends TC= to Elmo

Requirements:
    pip install pyserial pyvjoy
    vJoy driver installed (https://github.com/jshafer817/vJoy/releases)
    com0com virtual COM pair (SimHub writes one end, this script reads the other)

See WHEEL_TO_GAME_SETUP.md for full configuration instructions.
"""

import serial
import threading
import time
import sys
import signal
import logging
import os
import asyncio
import json
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# USER CONFIGURATION — edit these to match your system
# ---------------------------------------------------------------------------

ELMO_PORT   = "COM3"     # USB serial port for Elmo drive (Device Manager → COMx)
SIMHUB_PORT = "COM11"    # com0com virtual pair RECEIVE end (SimHub writes to COM10)
SIMHUB_WS_URL = "ws://127.0.0.1:8888"

ELMO_BAUD   = 115200
SIMHUB_BAUD = 115200

# Steering range: ±MAX_POSITION_COUNTS encoder counts = full lock-to-lock
# Must match PL[1] / PL[2] set in EAS II (use the absolute value)
MAX_POSITION_COUNTS = 204800

# Torque scaling: SimHub outputs ±10000; this maps that to ±MAX_TC in Elmo units
# Start LOW (200–500) and increase gradually. Never exceed ~70 % of motor rated current.
MAX_TC = 300

# vJoy device number (1-based, as configured in vJoy Config)
VJOY_DEVICE_ID = 1

# Polling interval for position + torque update loop (seconds)
# 0.005 = 200 Hz; reduce if you see USB serial overrun errors
LOOP_INTERVAL = 0.005

# Centre-deadband for SimHub FFB: values ±DEADBAND are clamped to 0
# Reduces centre chatter. Set to 0 to disable.
FFB_DEADBAND = 50

# FFB source mode: websocket (recommended), serial (com0com), inject (test profile)
FFB_SOURCE = "websocket"
SIMHUB_HTTP_URL = "http://127.0.0.1:8888/api/GetGameData"

# Optional test injection profile used by wheel_e2e_test.py
FFB_INJECT_SEQUENCE = ""
FFB_INJECT_HOLD_LOOPS = 80

# Environment overrides for unattended launchers.
ELMO_PORT = os.environ.get("ELMO_PORT", ELMO_PORT)
SIMHUB_PORT = os.environ.get("SIMHUB_PORT", SIMHUB_PORT)
MAX_POSITION_COUNTS = int(os.environ.get("MAX_POSITION_COUNTS", str(MAX_POSITION_COUNTS)))
MAX_TC = int(os.environ.get("MAX_TC", str(MAX_TC)))
LOOP_INTERVAL = float(os.environ.get("LOOP_INTERVAL", str(LOOP_INTERVAL)))
FFB_DEADBAND = int(os.environ.get("FFB_DEADBAND", str(FFB_DEADBAND)))
SIMHUB_WS_URL = os.environ.get("SIMHUB_WS_URL", SIMHUB_WS_URL)
SIMHUB_HTTP_URL = os.environ.get("SIMHUB_HTTP_URL", SIMHUB_HTTP_URL)
FFB_SOURCE = os.environ.get("FFB_SOURCE", FFB_SOURCE).strip().lower()
FFB_INJECT_SEQUENCE = os.environ.get("FFB_INJECT_SEQUENCE", FFB_INJECT_SEQUENCE).strip()
FFB_INJECT_HOLD_LOOPS = int(os.environ.get("FFB_INJECT_HOLD_LOOPS", str(FFB_INJECT_HOLD_LOOPS)))
LOCK_FILE = os.environ.get(
    "ELMO_BRIDGE_LOCK",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".elmo_ffb_bridge.lock"),
)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_single_instance_lock() -> None:
    # Atomic create avoids races when two launchers start at the same time.
    for _ in range(2):
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            try:
                with open(LOCK_FILE, "r", encoding="ascii") as f:
                    owner_pid = int((f.read() or "0").strip())
            except Exception:
                owner_pid = 0

            if owner_pid and _pid_alive(owner_pid):
                raise RuntimeError(f"Bridge already running with PID {owner_pid}. Lock file: {LOCK_FILE}")

            try:
                os.remove(LOCK_FILE)
            except OSError:
                pass

    raise RuntimeError(f"Could not acquire bridge lock: {LOCK_FILE}")


def release_single_instance_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r", encoding="ascii") as f:
                owner_pid = int((f.read() or "0").strip())
            if owner_pid == os.getpid():
                os.remove(LOCK_FILE)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Elmo ASCII protocol helpers
# ---------------------------------------------------------------------------

def elmo_send(ser: serial.Serial, cmd: str) -> str:
    """Send a command and return the response (best-effort, non-blocking read)."""
    ser.write((cmd + "\r\n").encode("ascii"))
    time.sleep(0.002)
    raw = ser.read(ser.in_waiting or 64)
    return raw.decode("ascii", errors="replace").strip()


def elmo_motor_on(ser: serial.Serial) -> None:
    resp = elmo_send(ser, "MO=1")
    log.info("MO=1 → %s", resp)


def elmo_motor_off(ser: serial.Serial) -> None:
    resp = elmo_send(ser, "MO=0")
    log.info("MO=0 → %s", resp)


def elmo_set_torque(ser: serial.Serial, value: int) -> None:
    """Set torque command. value in raw Elmo TC units (+/-)."""
    ser.write(f"TC={value}\r\n".encode("ascii"))
    # No response read here — fire-and-forget for low latency


def elmo_get_position(ser: serial.Serial) -> int:
    """Read encoder position in counts. Returns 0 on parse failure."""
    ser.write(b"PX\r\n")
    time.sleep(0.002)
    raw = ser.read(ser.in_waiting or 32).decode("ascii", errors="replace").strip()
    # Response format:  "PX=12345;"  or  "12345"
    try:
        val = raw.split("=")[-1].rstrip(";").strip()
        return int(val)
    except (ValueError, IndexError):
        return 0


# ---------------------------------------------------------------------------
# SimHub serial reader (runs in background thread)
# ---------------------------------------------------------------------------

class SimHubReader:
    """
    Reads FFB values from the SimHub custom serial port.

    Expected line format (configure in SimHub → Custom Serial output formula):
        $[ffb]$

    Which produces lines like:
        4752
        -2310
        0

    Range is ±10000 by default in SimHub. This class stores the latest value
    in self.ffb_value (thread-safe via a lock).
    """

    def __init__(self, port: str, baud: int):
        self._port = port
        self._baud = baud
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self._ffb_value: int = 0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._ser = serial.Serial(self._port, self._baud, timeout=0.05)
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True, name="simhub-reader")
        self._thread.start()
        log.info("SimHub reader started on %s @ %d baud", self._port, self._baud)

    def stop(self) -> None:
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()

    @property
    def ffb_value(self) -> int:
        with self._lock:
            return self._ffb_value

    def _reader_loop(self) -> None:
        buf = b""
        while self._running:
            try:
                chunk = self._ser.read(128)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._parse_line(line.strip())
            except serial.SerialException as exc:
                log.warning("SimHub serial error: %s", exc)
                time.sleep(0.1)
            except Exception as exc:
                log.debug("SimHub parse error: %s", exc)

    def _parse_line(self, line: bytes) -> None:
        if not line:
            return
        try:
            val = int(line)
            # Apply deadband
            if abs(val) <= FFB_DEADBAND:
                val = 0
            with self._lock:
                self._ffb_value = val
        except ValueError:
            pass  # Non-numeric lines (headers etc.) are ignored


class SimHubWebSocketReader:
    """Read force values from SimHub WebSocket stream (port 8888 by default)."""

    def __init__(self, ws_url: str):
        self._ws_url = ws_url
        self._lock = threading.Lock()
        self._ffb_value: int = 0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="simhub-ws")
        self._thread.start()
        log.info("SimHub WebSocket reader started on %s", self._ws_url)

    def stop(self) -> None:
        self._running = False

    @property
    def ffb_value(self) -> int:
        with self._lock:
            return self._ffb_value

    def _thread_main(self) -> None:
        asyncio.run(self._ws_loop())

    async def _ws_loop(self) -> None:
        import websockets

        while self._running:
            try:
                async with websockets.connect(self._ws_url, ping_interval=10, ping_timeout=10) as ws:
                    while self._running:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        parsed = self._extract_force_value(msg)
                        if parsed is None:
                            continue
                        if abs(parsed) <= FFB_DEADBAND:
                            parsed = 0
                        with self._lock:
                            self._ffb_value = parsed
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                log.warning("SimHub WebSocket error: %s", exc)
                await asyncio.sleep(0.5)

    def _extract_force_value(self, msg) -> int | None:
        if isinstance(msg, (bytes, bytearray)):
            try:
                msg = msg.decode("utf-8", errors="ignore")
            except Exception:
                return None

        text = str(msg).strip()
        if not text:
            return None

        try:
            return int(text)
        except ValueError:
            pass

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None

        num = self._find_numeric(payload)
        return int(num) if num is not None else None

    def _find_numeric(self, obj):
        if isinstance(obj, (int, float)):
            return obj

        if isinstance(obj, dict):
            preferred = ("ffb", "force", "value", "ffbValue", "signal")
            for key in preferred:
                if key in obj and isinstance(obj[key], (int, float)):
                    return obj[key]
            for value in obj.values():
                found = self._find_numeric(value)
                if found is not None:
                    return found

        if isinstance(obj, list):
            for item in obj:
                found = self._find_numeric(item)
                if found is not None:
                    return found

        return None


class InjectReader:
    """Deterministic FFB generator for unattended tests."""

    def __init__(self, sequence_text: str, hold_loops: int):
        parts = [p.strip() for p in sequence_text.split(",") if p.strip()]
        self._sequence = [int(p) for p in parts] if parts else [0]
        self._hold = max(1, hold_loops)
        self._idx = 0
        self._countdown = self._hold
        self._ffb_value = self._sequence[0]

    def start(self) -> None:
        log.info("Inject mode active with %d points, hold %d loops", len(self._sequence), self._hold)

    def stop(self) -> None:
        return

    @property
    def ffb_value(self) -> int:
        val = self._ffb_value
        self._countdown -= 1
        if self._countdown <= 0:
            self._idx = (self._idx + 1) % len(self._sequence)
            self._ffb_value = self._sequence[self._idx]
            self._countdown = self._hold
        return val


class SimHubHttpReader:
    """Poll SimHub HTTP API for game data and infer an FFB-like signal."""

    def __init__(self, url: str, poll_interval: float = 0.02):
        self._url = url
        self._poll_interval = max(0.01, poll_interval)
        self._lock = threading.Lock()
        self._ffb_value: int = 0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="simhub-http")
        self._thread.start()
        log.info("SimHub HTTP reader started on %s", self._url)

    def stop(self) -> None:
        self._running = False

    @property
    def ffb_value(self) -> int:
        with self._lock:
            return self._ffb_value

    def _loop(self) -> None:
        while self._running:
            try:
                req = urllib.request.Request(self._url, headers={"User-Agent": "elmo-ffb-bridge/1.0"})
                with urllib.request.urlopen(req, timeout=0.8) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                payload = json.loads(raw)
                parsed = self._extract_force_value(payload)
                if parsed is None:
                    parsed = 0
                if abs(parsed) <= FFB_DEADBAND:
                    parsed = 0
                with self._lock:
                    self._ffb_value = parsed
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                log.debug("SimHub HTTP read error: %s", exc)
            except Exception as exc:
                log.debug("SimHub HTTP unexpected error: %s", exc)
            time.sleep(self._poll_interval)

    def _extract_force_value(self, payload) -> int | None:
        # Prefer common force-feedback-ish keys first.
        preferred = (
            "ffb", "force", "forcefeedback", "finalforcefeedback", "finalforce",
            "steeringforce", "wheelforce", "torque", "ffbvalue",
        )

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    lk = str(k).lower()
                    if any(p in lk for p in preferred) and isinstance(v, (int, float)):
                        return int(v)
                for v in obj.values():
                    found = walk(v)
                    if found is not None:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = walk(item)
                    if found is not None:
                        return found
            return None

        return walk(payload)


# ---------------------------------------------------------------------------
# vJoy position reporter
# ---------------------------------------------------------------------------

def position_to_vjoy_axis(position_counts: int) -> int:
    """
    Map encoder counts (±MAX_POSITION_COUNTS) to vJoy axis value (1–32767).
    vJoy expects an integer in the range [1, 32767].
    """
    clamped = max(-MAX_POSITION_COUNTS, min(MAX_POSITION_COUNTS, position_counts))
    normalized = clamped / MAX_POSITION_COUNTS          # -1.0 … +1.0
    axis_val = int((normalized + 1.0) / 2.0 * 32766) + 1   # 1 … 32767
    return axis_val


def ffb_to_tc(ffb_value: int) -> int:
    """
    Scale SimHub FFB value (±10000) to Elmo torque command (±MAX_TC).
    """
    scaled = int(ffb_value / 10000 * MAX_TC)
    return max(-MAX_TC, min(MAX_TC, scaled))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    import pyvjoy

    try:
        acquire_single_instance_lock()
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    log.info("=== Elmo FFB Bridge starting ===")
    log.info("Elmo port : %s  @ %d", ELMO_PORT, ELMO_BAUD)
    log.info("FFB source : %s", FFB_SOURCE)
    log.info("SimHub port: %s @ %d", SIMHUB_PORT, SIMHUB_BAUD)
    log.info("SimHub WS  : %s", SIMHUB_WS_URL)
    log.info("SimHub HTTP: %s", SIMHUB_HTTP_URL)
    log.info("MAX_TC     : ±%d", MAX_TC)
    log.info("Steer range: ±%d counts", MAX_POSITION_COUNTS)

    # --- vJoy ---
    try:
        vjoy = pyvjoy.VJoyDevice(VJOY_DEVICE_ID)
        log.info("vJoy device %d acquired", VJOY_DEVICE_ID)
    except Exception as exc:
        log.error("Failed to open vJoy device %d: %s", VJOY_DEVICE_ID, exc)
        log.error("→ Make sure vJoy is installed and Device %d is enabled in vJoy Config", VJOY_DEVICE_ID)
        sys.exit(1)

    # --- Elmo ---
    try:
        elmo = serial.Serial(ELMO_PORT, ELMO_BAUD, timeout=0.02)
        time.sleep(0.5)
        log.info("Elmo serial open: %s", ELMO_PORT)
    except serial.SerialException as exc:
        log.error("Cannot open Elmo port %s: %s", ELMO_PORT, exc)
        sys.exit(1)

    # Check motor is in torque mode
    um = elmo_send(elmo, "UM")
    log.info("Elmo UM = %s (expected 4 for torque mode)", um)

    # Enable motor
    elmo_motor_on(elmo)
    log.info("Motor enabled (MO=1)")

    # --- Force source reader ---
    simhub = None
    if FFB_SOURCE == "serial":
        simhub = SimHubReader(SIMHUB_PORT, SIMHUB_BAUD)
        try:
            simhub.start()
        except serial.SerialException as exc:
            log.warning("Cannot open SimHub serial port %s: %s — FFB will be disabled", SIMHUB_PORT, exc)
            simhub = None
    elif FFB_SOURCE == "inject":
        simhub = InjectReader(FFB_INJECT_SEQUENCE, FFB_INJECT_HOLD_LOOPS)
        simhub.start()
    elif FFB_SOURCE == "http":
        simhub = SimHubHttpReader(SIMHUB_HTTP_URL)
        simhub.start()
    else:
        # websocket mode by default, with automatic fallback to HTTP polling.
        try:
            simhub = SimHubWebSocketReader(SIMHUB_WS_URL)
            simhub.start()
            time.sleep(0.25)
        except Exception as exc:
            log.warning("WebSocket mode failed to start (%s), falling back to HTTP", exc)
            simhub = SimHubHttpReader(SIMHUB_HTTP_URL)
            simhub.start()

    # --- Graceful shutdown ---
    shutdown_event = threading.Event()

    def _on_signal(sig, frame):
        log.info("Shutdown signal received")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # --- Main loop ---
    log.info("Bridge running — Ctrl+C to stop")
    loop_count = 0
    last_tc = 0

    try:
        while not shutdown_event.is_set():
            t0 = time.perf_counter()

            # 1. Read wheel angle from Elmo
            pos = elmo_get_position(elmo)

            # 2. Update vJoy steering axis
            axis_val = position_to_vjoy_axis(pos)
            vjoy.set_axis(pyvjoy.HID_USAGE_X, axis_val)

            # 3. Get FFB from SimHub, send to Elmo
            ffb_raw = simhub.ffb_value if simhub else 0
            tc = ffb_to_tc(ffb_raw)
            if tc != last_tc:
                elmo_set_torque(elmo, tc)
                last_tc = tc

            # Diagnostics every ~2 seconds
            loop_count += 1
            if loop_count % 400 == 0:
                log.info("pos=%7d  axis=%5d  ffb_raw=%6d  TC=%5d",
                         pos, axis_val, ffb_raw, tc)

            # Maintain loop rate
            elapsed = time.perf_counter() - t0
            sleep_for = LOOP_INTERVAL - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    finally:
        log.info("Shutting down — zeroing torque and disabling motor")
        elmo_set_torque(elmo, 0)
        time.sleep(0.05)
        elmo_motor_off(elmo)
        elmo.close()
        if simhub:
            simhub.stop()
        release_single_instance_lock()
        log.info("Done.")


if __name__ == "__main__":
    main()
