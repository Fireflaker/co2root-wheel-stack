#!/usr/bin/env python3
"""Single-master control GUI for the wheel toolchain.

This app centralizes runtime control so only one bridge path is active at a time.
It is intentionally safety-first: panic stop and motor release are one click away.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
except Exception:  # pragma: no cover
    serial = None


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
MUTEX_NAME = "Global\\Co2Root_MasterControlGUI"
LOG_DIR = ROOT / "logs" / "master_gui"


class MasterLock:
    def __init__(self, name: str):
        self.name = name
        self.handle = None

    def __enter__(self):
        self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise RuntimeError("CreateMutex failed")
        err = ctypes.windll.kernel32.GetLastError()
        if err == 183:  # ERROR_ALREADY_EXISTS
            raise RuntimeError("Master GUI already running")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)


def ps_kill_conflicts() -> str:
    cmd = (
        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'adapter_project[/\\\\]adapter_main.py|"
        "wheel_sim_bridge.py|elmo_ffb_bridge.py' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
        "\"STOPPED $($_.ProcessId)\" } | Out-String"
    )
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return (res.stdout or "").strip() or "No conflicting bridge process found."


def start_simhub() -> str:
    simhub_exe = r"C:\Program Files (x86)\SimHub\SimHubWPF.exe"
    if not Path(simhub_exe).exists():
        return "SimHub executable not found in default path."
    subprocess.run(["powershell", "-NoProfile", "-Command", f'Start-Process "{simhub_exe}"'], timeout=5)
    return "SimHub start triggered."


def start_lfs() -> str:
    lfs_link = (
        r"C:\Users\hotmo\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Live for Speed\LFS.lnk"
    )
    if not Path(lfs_link).exists():
        return "LFS shortcut not found."
    subprocess.run(["powershell", "-NoProfile", "-Command", f'Start-Process "{lfs_link}"'], timeout=5)
    return "LFS start triggered."


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Co2Root Wheel Master Control")
        self.root.geometry("980x670")
        self.proc: subprocess.Popen[str] | None = None
        self.proc_name = ""
        self.cfg = self._load_cfg()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.session_log = LOG_DIR / f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        self._build_ui()
        self._heartbeat()

    def _load_cfg(self) -> dict[str, Any]:
        if not CONFIG_PATH.exists():
            raise RuntimeError(f"Missing config: {CONFIG_PATH}")
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def _save_cfg(self) -> None:
        CONFIG_PATH.write_text(json.dumps(self.cfg, indent=4), encoding="ascii")

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=10, pady=10)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(top, text="Status:").pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self.status_var, foreground="#006400").pack(side=tk.LEFT, padx=8)

        cfg = ttk.LabelFrame(self.root, text="Config")
        cfg.pack(fill=tk.X, padx=10, pady=6)

        self.src_var = tk.StringVar(value=str(self.cfg.get("sim_source", "websocket")))
        ttk.Label(cfg, text="Sim source").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(cfg, textvariable=self.src_var, values=["websocket", "http", "serial", "inject"], width=14, state="readonly").grid(row=0, column=1, padx=6, pady=6, sticky="w")

        self.auto_on_var = tk.BooleanVar(value=bool(self.cfg.get("auto_motor_on", False)))
        ttk.Checkbutton(cfg, text="auto_motor_on", variable=self.auto_on_var).grid(row=0, column=2, padx=6, pady=6, sticky="w")

        self.off_on_exit_var = tk.BooleanVar(value=bool(self.cfg.get("motor_off_on_exit", True)))
        ttk.Checkbutton(cfg, text="motor_off_on_exit", variable=self.off_on_exit_var).grid(row=0, column=3, padx=6, pady=6, sticky="w")

        self.loop_var = tk.StringVar(value=str(self.cfg.get("loop_hz", 200)))
        ttk.Label(cfg, text="loop_hz").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.loop_var, width=10).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        self.px_skip_var = tk.StringVar(value=str(self.cfg.get("px_poll_every_loops", 1)))
        ttk.Label(cfg, text="px_poll_every_loops").grid(row=1, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.px_skip_var, width=10).grid(row=1, column=3, padx=6, pady=6, sticky="w")

        btns = ttk.LabelFrame(self.root, text="Master Actions")
        btns.pack(fill=tk.X, padx=10, pady=6)

        ttk.Button(btns, text="Save Config", command=self.save_config).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(btns, text="Kill Conflicts", command=self.kill_conflicts).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(btns, text="Probe Drive", command=self.probe_drive).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(btns, text="Release Motor", command=self.release_motor).grid(row=0, column=3, padx=6, pady=6)
        ttk.Button(btns, text="Start Adapter", command=self.start_adapter).grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(btns, text="Start Safe vJoy", command=self.start_safe_vjoy).grid(row=0, column=5, padx=6, pady=6)
        ttk.Button(btns, text="Stop Managed", command=self.stop_managed).grid(row=0, column=6, padx=6, pady=6)
        ttk.Button(btns, text="Health Check", command=self.health_check).grid(row=1, column=0, padx=6, pady=6)
        ttk.Button(btns, text="One-Click Safe Bring-up", command=self.one_click_safe_bringup).grid(row=1, column=1, padx=6, pady=6, columnspan=2, sticky="we")
        ttk.Button(btns, text="Open Logs Folder", command=self.open_logs_folder).grid(row=1, column=3, padx=6, pady=6)

        ext = ttk.LabelFrame(self.root, text="External")
        ext.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(ext, text="Start SimHub", command=lambda: self._log(start_simhub())).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(ext, text="Start LFS", command=lambda: self._log(start_lfs())).grid(row=0, column=1, padx=6, pady=6)

        safety = ttk.LabelFrame(self.root, text="Panic")
        safety.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(safety, text="PANIC STOP", command=self.panic_stop).pack(side=tk.LEFT, padx=8, pady=8)

        comms = ttk.LabelFrame(self.root, text="Elmo Comms")
        comms.pack(fill=tk.BOTH, expand=False, padx=10, pady=(8, 4))
        self.comms_log = tk.Text(comms, height=9)
        self.comms_log.pack(fill=tk.BOTH, expand=True)

        logf = ttk.LabelFrame(self.root, text="Log")
        logf.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 8))
        self.log = tk.Text(logf, height=16)
        self.log.pack(fill=tk.BOTH, expand=True)
        self._log("Master GUI ready. Use Kill Conflicts -> Probe Drive -> Start Safe vJoy/Start Adapter.")

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        try:
            with self.session_log.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

        def append() -> None:
            self.log.insert(tk.END, line + "\n")
            self.log.see(tk.END)

        try:
            self.root.after(0, append)
        except Exception:
            pass

    def _elmo_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"

        def append() -> None:
            self.comms_log.insert(tk.END, line + "\n")
            self.comms_log.see(tk.END)

        try:
            self.root.after(0, append)
        except Exception:
            pass

    def _elmo_exchange(self, sp: Any, cmd: str, read_wait_s: float = 0.12) -> str:
        sp.reset_input_buffer()
        sp.write((cmd + "\r").encode("ascii"))
        time.sleep(read_wait_s)
        resp = sp.read(sp.in_waiting or 128).decode("ascii", errors="replace").strip()
        self._elmo_log(f"{cmd} => {resp or '<no-response>'}")
        return resp

    def save_config(self) -> None:
        try:
            self.cfg["sim_source"] = self.src_var.get().strip()
            self.cfg["auto_motor_on"] = bool(self.auto_on_var.get())
            self.cfg["motor_off_on_exit"] = bool(self.off_on_exit_var.get())
            self.cfg["loop_hz"] = int(self.loop_var.get().strip())
            self.cfg["px_poll_every_loops"] = int(self.px_skip_var.get().strip())
            self._save_cfg()
            self._log("Config saved.")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def kill_conflicts(self) -> None:
        try:
            out = ps_kill_conflicts()
            self._log(out)
        except Exception as exc:
            self._log(f"Kill conflicts failed: {exc}")

    def _is_port_open(self, host: str, port: int, timeout_s: float = 0.25) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True
        except Exception:
            return False

    def _can_open_serial(self, port: str, baud: int) -> bool:
        if serial is None:
            return False
        try:
            with serial.Serial(port, baud, timeout=0.1):
                return True
        except Exception:
            return False

    def health_check(self) -> None:
        port = str(self.cfg.get("elmo_port", "COM13"))
        baud = int(self.cfg.get("elmo_baud", 115200))
        ws_url = str(self.cfg.get("sim_ws_url", "ws://127.0.0.1:8888"))
        simhub_port_ok = self._is_port_open("127.0.0.1", 8888)
        com_ok = self._can_open_serial(port, baud)
        self._log(f"HEALTH simhub_port_8888={'OK' if simhub_port_ok else 'DOWN'}")
        self._log(f"HEALTH {port}@{baud}={'OK' if com_ok else 'BUSY/DOWN'}")
        self._log(f"HEALTH sim_source={self.cfg.get('sim_source')} sim_ws_url={ws_url}")

    def one_click_safe_bringup(self) -> None:
        def run() -> None:
            self._log("One-click safe bring-up starting.")
            self.save_config()
            self.kill_conflicts()
            self.health_check()
            self.release_motor()
            time.sleep(0.2)
            self._log(start_simhub())
            time.sleep(0.2)
            self._log(start_lfs())
            self._log("One-click safe bring-up complete. Choose Start Safe vJoy first, then Start Adapter when ready.")

        threading.Thread(target=run, daemon=True).start()

    def open_logs_folder(self) -> None:
        try:
            os.startfile(str(LOG_DIR))
        except Exception as exc:
            self._log(f"Open logs folder failed: {exc}")

    def probe_drive(self) -> None:
        if serial is None:
            self._log("pyserial unavailable.")
            return
        port = str(self.cfg.get("elmo_port", "COM13"))
        baud = int(self.cfg.get("elmo_baud", 115200))

        def run_probe():
            try:
                with serial.Serial(port, baud, timeout=0.25) as sp:
                    time.sleep(0.1)
                    for cmd in ("MO", "EC", "UM", "PX"):
                        resp = self._elmo_exchange(sp, cmd, read_wait_s=0.15)
                        self._log(f"{cmd} => {resp or '<no-response>'}")
            except Exception as exc:
                self._log(f"Probe failed: {exc}")
                self._elmo_log(f"Probe failed: {exc}")

        threading.Thread(target=run_probe, daemon=True).start()

    def release_motor(self) -> None:
        if serial is None:
            self._log("pyserial unavailable.")
            return
        port = str(self.cfg.get("elmo_port", "COM13"))
        baud = int(self.cfg.get("elmo_baud", 115200))

        def run_release():
            try:
                with serial.Serial(port, baud, timeout=0.25) as sp:
                    time.sleep(0.1)
                    for cmd in ("ST", "TC=0", "MO=0", "MO"):
                        resp = self._elmo_exchange(sp, cmd, read_wait_s=0.12)
                        self._log(f"{cmd} => {resp or '<no-response>'}")
                self._log("Motor release sequence done.")
                self._elmo_log("Release sequence done.")
            except Exception as exc:
                self._log(f"Release failed: {exc}")
                self._elmo_log(f"Release failed: {exc}")

        threading.Thread(target=run_release, daemon=True).start()

    def _start_managed(self, args: list[str], name: str) -> None:
        self.stop_managed()
        self.kill_conflicts()
        try:
            self.proc = subprocess.Popen(
                args,
                cwd=str(ROOT),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.proc_name = name
            self.status_var.set(f"Running: {name}")
            self._log(f"Started {name}: {' '.join(args)}")
            threading.Thread(target=self._pump_logs, daemon=True).start()
        except Exception as exc:
            self._log(f"Start {name} failed: {exc}")

    def _pump_logs(self) -> None:
        if not self.proc or not self.proc.stdout:
            return
        try:
            for line in self.proc.stdout:
                if line:
                    self._log(line.rstrip())
        except Exception:
            pass

    def start_adapter(self) -> None:
        self.save_config()
        if str(self.cfg.get("sim_source", "")).lower() == "websocket" and not self._is_port_open("127.0.0.1", 8888):
            self._log("WARN sim_source=websocket but SimHub port 8888 is not reachable.")
        python_exe = str((ROOT.parent / ".venv" / "Scripts" / "python.exe").resolve())
        if not Path(python_exe).exists():
            python_exe = sys.executable
        self._start_managed([python_exe, str((ROOT / "adapter_main.py").resolve())], "adapter_main")

    def start_safe_vjoy(self) -> None:
        python_exe = str((ROOT.parent / ".venv" / "Scripts" / "python.exe").resolve())
        if not Path(python_exe).exists():
            python_exe = sys.executable
        self._start_managed([python_exe, str((ROOT / "wheel_sim_bridge.py").resolve()), "--mode", "vjoy"], "wheel_sim_bridge_safe")

    def stop_managed(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
                time.sleep(0.8)
                if self.proc.poll() is None:
                    self.proc.terminate()
                    time.sleep(0.5)
                if self.proc.poll() is None:
                    self.proc.kill()
                self._log(f"Stopped managed process: {self.proc_name}")
            except Exception as exc:
                self._log(f"Stop managed failed: {exc}")
        self.proc = None
        self.proc_name = ""
        self.status_var.set("Idle")

    def on_close(self) -> None:
        self.stop_managed()
        if bool(self.cfg.get("motor_off_on_exit", True)):
            self.release_motor()
            self._log("Window close: motor_off_on_exit enabled, release sequence sent.")
        self.root.destroy()

    def panic_stop(self) -> None:
        self.stop_managed()
        self.kill_conflicts()
        self.release_motor()
        self._log("PANIC STOP completed.")

    def _heartbeat(self) -> None:
        if self.proc and self.proc.poll() is not None:
            code = self.proc.returncode
            self._log(f"Managed process exited with code {code}")
            self.proc = None
            self.proc_name = ""
            self.status_var.set("Idle")
        self.root.after(800, self._heartbeat)


def main() -> int:
    try:
        lock = MasterLock(MUTEX_NAME)
        lock.__enter__()
    except Exception as exc:
        messagebox.showerror("Master Control", f"Cannot start: {exc}")
        return 1

    try:
        root = tk.Tk()
        app = App(root)
        root.protocol("WM_DELETE_WINDOW", app.on_close)
        root.mainloop()
    finally:
        try:
            lock.__exit__(None, None, None)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
