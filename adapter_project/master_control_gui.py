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
import re
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

from elmo_transport import build_elmo_client, scan_ethercat_bus
from vjoy_state import save_input_state


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
MUTEX_NAME = "Global\\Co2Root_MasterControlGUI"
LOG_DIR = ROOT / "logs" / "master_gui"
VJOY_INTERFACE_DLL = Path(r"C:\Program Files\vJoy\x64\vJoyInterface.dll")


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
        "$pythonCmdPattern = 'adapter_project[/\\\\]adapter_main\\.py|wheel_sim_bridge\\.py|"
        "elmo_ffb_bridge\\.py|verify_adapter_control\\.py|spin_and_ffb_verify\\.py|"
        "direct_rotation_sweep\\.py|il_pulse_verify\\.py|tc_diagnostics\\.py|"
        "torque_path_sweep\\.py|motion_ref_discovery\\.py|um_tc_discovery\\.py|"
        "wheel_poller_1khz(?:_fast)?\\.py|encoder_roundtrip_loop(?:_v2)?\\.py|"
        "start_wheel_bridge\\.py|local_screen_setup[/\\\\]wheel_spin_demo\\.py'; "
        "$powershellCmdPattern = 'run_wheel_demo\\.ps1|run_adapter_with_demo\\.ps1|"
        "motor_cleanup_and_release\\.ps1|wheel_ops\\.ps1|start_adapter\\.ps1|start_master_gui\\.ps1'; "
        "$titlePattern = 'Elmo Application Studio|\\bEAS\\b|Composer'; "
        "$killed = New-Object System.Collections.Generic.List[string]; "
        "Get-CimInstance Win32_Process -Filter \"name='python.exe' OR name='pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -match $pythonCmdPattern } | "
        "ForEach-Object { "
        "  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $killed.Add(\"python PID=$($_.ProcessId)\") } catch {} "
        "}; "
        "Get-CimInstance Win32_Process -Filter \"name='powershell.exe' OR name='pwsh.exe'\" | "
        "Where-Object { $_.CommandLine -match $powershellCmdPattern -and $_.ProcessId -ne $PID } | "
        "ForEach-Object { "
        "  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $killed.Add(\"powershell PID=$($_.ProcessId)\") } catch {} "
        "}; "
        "Get-Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowTitle -match $titlePattern -or $_.ProcessName -match 'StudioManager|Composer|EAS' } | "
        "ForEach-Object { "
        "  try { Stop-Process -Id $_.Id -Force -ErrorAction Stop; $killed.Add(\"$($_.ProcessName) PID=$($_.Id)\") } catch {} "
        "}; "
        "if ($killed.Count -eq 0) { 'No conflicting bridge process found.' } else { 'STOPPED ' + ($killed -join ', ') }"
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
    os.startfile(simhub_exe)
    return "SimHub start triggered."


def start_lfs() -> str:
    lfs_link = (
        r"C:\Users\hotmo\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Live for Speed\LFS.lnk"
    )
    if not Path(lfs_link).exists():
        return "LFS shortcut not found."
    os.startfile(lfs_link)
    return "LFS start triggered."


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Co2Root Wheel Master Control")
        self.root.geometry("1180x820")
        self.proc: subprocess.Popen[str] | None = None
        self.proc_name = ""
        self.cfg = self._load_cfg()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.session_log = LOG_DIR / f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.throttle_var = tk.DoubleVar(value=0.0)
        self.brake_var = tk.DoubleVar(value=0.0)
        self.transport_var = tk.StringVar(value=str(self.cfg.get("elmo_transport", "serial")))
        self.cmd_mode_var = tk.StringVar(value=str(self.cfg.get("elmo_command_mode", "pr")))
        self.ffb_strength_var = tk.StringVar(value=str(self.cfg.get("ffb_strength", 1.0)))
        self.max_current_a_var = tk.StringVar(value=str(self.cfg.get("max_current_a", 0.0)))
        self.motor_current_utilization_var = tk.StringVar(value=str(self.cfg.get("motor_current_utilization", 0.5)))
        self.min_current_a_var = tk.StringVar(value=str(self.cfg.get("min_current_a", 0.1)))
        self.current_cmd_scale_var = tk.StringVar(value=str(self.cfg.get("current_cmd_scale", 1000.0)))
        self.max_il_step_var = tk.StringVar(value=str(self.cfg.get("max_il_step_per_loop", 100)))
        self.max_pr_per_loop_var = tk.StringVar(value=str(self.cfg.get("max_pr_per_loop", 220)))
        self.max_pr_step_var = tk.StringVar(value=str(self.cfg.get("max_pr_step_per_loop", 16)))
        self.max_tc_var = tk.StringVar(value=str(self.cfg.get("max_tc", 300)))
        self.max_tc_step_var = tk.StringVar(value=str(self.cfg.get("max_tc_step_per_loop", 12)))
        self.ffb_deadband_var = tk.StringVar(value=str(self.cfg.get("ffb_deadband", 50)))
        self.ffb_input_max_var = tk.StringVar(value=str(self.cfg.get("ffb_input_max", 10000)))
        self.vjoy_device_id_var = tk.StringVar(value=str(self.cfg.get("vjoy_device_id", 1)))
        self.wheel_lock_deg_var = tk.StringVar(value=str(self.cfg.get("wheel_lock_deg", 540.0)))
        self.inject_fallback_var = tk.BooleanVar(value=bool(self.cfg.get("ffb_fallback_to_inject", True)))
        self.fallback_after_var = tk.StringVar(value=str(self.cfg.get("ffb_fallback_after_s", 1.0)))
        self.idle_release_var = tk.BooleanVar(value=bool(self.cfg.get("release_motor_on_idle_ffb", False)))
        self.ethercat_degraded_enable_var = tk.BooleanVar(value=bool(self.cfg.get("ethercat_allow_degraded_enable", False)))
        self.test_current_var = tk.StringVar(value="280")
        self.spin_jv_var = tk.StringVar(value="1500")
        self.counts_per_rev_var = tk.StringVar(value="131072")
        self.bench_current_a_var = tk.StringVar(value="1.0")
        self.bench_hold_ms_var = tk.StringVar(value="250")
        self.ethercat_adapter_var = tk.StringVar(value=str(self.cfg.get("ethercat_adapter_match", "Realtek Gaming USB 2.5GbE Family Controller")))
        self.ethercat_slave_var = tk.StringVar(value=str(self.cfg.get("ethercat_slave_index", 1)))
        self.ethercat_profile_velocity_var = tk.StringVar(value=str(self.cfg.get("ethercat_profile_velocity", 120000)))
        self.ethercat_profile_accel_var = tk.StringVar(value=str(self.cfg.get("ethercat_profile_acceleration", 250000)))
        self.ethercat_profile_decel_var = tk.StringVar(value=str(self.cfg.get("ethercat_profile_deceleration", 250000)))

        self._build_ui()
        self._write_vjoy_pedal_state(log_change=False)
        self._heartbeat()

    def _load_cfg(self) -> dict[str, Any]:
        if not CONFIG_PATH.exists():
            raise RuntimeError(f"Missing config: {CONFIG_PATH}")
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def _save_cfg(self) -> None:
        CONFIG_PATH.write_text(json.dumps(self.cfg, indent=4), encoding="ascii")

    def _is_direct_vjoy_ffb(self) -> bool:
        return self.src_var.get().strip().lower() == "vjoy_ffb"

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=10, pady=10)

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(top, text="Status:").pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self.status_var, foreground="#006400").pack(side=tk.LEFT, padx=8)

        cfg = ttk.LabelFrame(self.root, text="Config")
        cfg.pack(fill=tk.X, padx=10, pady=6)

        ttk.Label(cfg, text="Drive transport").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(cfg, textvariable=self.transport_var, values=["ethercat", "serial"], width=14, state="readonly").grid(row=0, column=1, padx=6, pady=6, sticky="w")
        self.src_var = tk.StringVar(value=str(self.cfg.get("sim_source", "websocket")))
        ttk.Label(cfg, text="Sim source").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Combobox(cfg, textvariable=self.src_var, values=["websocket", "http", "serial", "inject", "vjoy_ffb"], width=14, state="readonly").grid(row=0, column=3, padx=6, pady=6, sticky="w")

        self.auto_on_var = tk.BooleanVar(value=bool(self.cfg.get("auto_motor_on", False)))
        ttk.Checkbutton(cfg, text="auto_motor_on", variable=self.auto_on_var).grid(row=0, column=4, padx=6, pady=6, sticky="w")

        self.off_on_exit_var = tk.BooleanVar(value=bool(self.cfg.get("motor_off_on_exit", True)))
        ttk.Checkbutton(cfg, text="motor_off_on_exit", variable=self.off_on_exit_var).grid(row=0, column=5, padx=6, pady=6, sticky="w")

        self.loop_var = tk.StringVar(value=str(self.cfg.get("loop_hz", 200)))
        ttk.Label(cfg, text="loop_hz").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.loop_var, width=10).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        self.px_skip_var = tk.StringVar(value=str(self.cfg.get("px_poll_every_loops", 1)))
        ttk.Label(cfg, text="px_poll_every_loops").grid(row=1, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.px_skip_var, width=10).grid(row=1, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(cfg, text="ethercat_adapter_match").grid(row=2, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.ethercat_adapter_var, width=38).grid(row=2, column=1, columnspan=3, padx=6, pady=6, sticky="we")
        ttk.Label(cfg, text="ethercat_slave_index").grid(row=2, column=4, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.ethercat_slave_var, width=10).grid(row=2, column=5, padx=6, pady=6, sticky="w")

        ttk.Label(cfg, text="ec_profile_velocity").grid(row=3, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.ethercat_profile_velocity_var, width=12).grid(row=3, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(cfg, text="ec_profile_accel").grid(row=3, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.ethercat_profile_accel_var, width=12).grid(row=3, column=3, padx=6, pady=6, sticky="w")
        ttk.Label(cfg, text="ec_profile_decel").grid(row=3, column=4, padx=6, pady=6, sticky="w")
        ttk.Entry(cfg, textvariable=self.ethercat_profile_decel_var, width=12).grid(row=3, column=5, padx=6, pady=6, sticky="w")
        ttk.Checkbutton(
            cfg,
            text="ethercat_allow_degraded_enable (bench only)",
            variable=self.ethercat_degraded_enable_var,
        ).grid(row=4, column=0, columnspan=3, padx=6, pady=6, sticky="w")
        ttk.Label(
            cfg,
            text="Allows switched-on fallback if full Operation Enabled is unavailable. Keep off for production.",
        ).grid(row=4, column=3, columnspan=3, padx=6, pady=6, sticky="w")

        tuning = ttk.LabelFrame(self.root, text="FFB And Output Mapping")
        tuning.pack(fill=tk.X, padx=10, pady=6)

        ttk.Label(tuning, text="elmo_command_mode").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Combobox(tuning, textvariable=self.cmd_mode_var, values=["pr", "il", "tc"], width=10, state="readonly").grid(row=0, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="ffb_strength").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.ffb_strength_var, width=10).grid(row=0, column=3, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="ffb_deadband").grid(row=0, column=4, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.ffb_deadband_var, width=10).grid(row=0, column=5, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="ffb_input_max").grid(row=0, column=6, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.ffb_input_max_var, width=10).grid(row=0, column=7, padx=6, pady=6, sticky="w")

        ttk.Label(tuning, text="max_current_a").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.max_current_a_var, width=10).grid(row=1, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="motor_current_utilization").grid(row=1, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.motor_current_utilization_var, width=10).grid(row=1, column=3, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="min_current_a").grid(row=1, column=4, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.min_current_a_var, width=10).grid(row=1, column=5, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="current_cmd_scale").grid(row=1, column=6, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.current_cmd_scale_var, width=10).grid(row=1, column=7, padx=6, pady=6, sticky="w")

        ttk.Label(tuning, text="max_il_step_per_loop").grid(row=2, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.max_il_step_var, width=10).grid(row=2, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="max_pr_per_loop").grid(row=2, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.max_pr_per_loop_var, width=10).grid(row=2, column=3, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="max_pr_step_per_loop").grid(row=2, column=4, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.max_pr_step_var, width=10).grid(row=2, column=5, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="wheel_lock_deg").grid(row=2, column=6, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.wheel_lock_deg_var, width=10).grid(row=2, column=7, padx=6, pady=6, sticky="w")

        ttk.Label(tuning, text="max_tc").grid(row=3, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.max_tc_var, width=10).grid(row=3, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="max_tc_step_per_loop").grid(row=3, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.max_tc_step_var, width=10).grid(row=3, column=3, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="vjoy_device_id").grid(row=3, column=4, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.vjoy_device_id_var, width=10).grid(row=3, column=5, padx=6, pady=6, sticky="w")
        ttk.Label(tuning, text="ffb_fallback_after_s").grid(row=3, column=6, padx=6, pady=6, sticky="w")
        ttk.Entry(tuning, textvariable=self.fallback_after_var, width=10).grid(row=3, column=7, padx=6, pady=6, sticky="w")

        ttk.Checkbutton(tuning, text="ffb_fallback_to_inject", variable=self.inject_fallback_var).grid(row=4, column=0, columnspan=2, padx=6, pady=6, sticky="w")
        ttk.Checkbutton(tuning, text="release_motor_on_idle_ffb", variable=self.idle_release_var).grid(row=4, column=2, columnspan=2, padx=6, pady=6, sticky="w")
        ttk.Label(
            tuning,
            text="Direct game FFB uses sim_source=vjoy_ffb. IL mode uses current-related fields; PR mode uses motion-reference fallback. TC remains hardware-dependent.",
        ).grid(row=4, column=4, columnspan=4, padx=6, pady=6, sticky="w")

        btns = ttk.LabelFrame(self.root, text="Master Actions")
        btns.pack(fill=tk.X, padx=10, pady=6)

        ttk.Button(btns, text="Save Config", command=self.save_config).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(btns, text="Kill Conflicts", command=self.kill_conflicts).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(btns, text="Probe Drive", command=self.probe_drive).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(btns, text="Scan EtherCAT", command=self.scan_ethercat).grid(row=0, column=3, padx=6, pady=6)
        ttk.Button(btns, text="Release Motor", command=self.release_motor).grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(btns, text="Start Adapter", command=self.start_adapter).grid(row=0, column=5, padx=6, pady=6)
        ttk.Button(btns, text="Start Safe vJoy", command=self.start_safe_vjoy).grid(row=0, column=6, padx=6, pady=6)
        ttk.Button(btns, text="Stop Managed", command=self.stop_managed).grid(row=0, column=7, padx=6, pady=6)
        ttk.Button(btns, text="Health Check", command=self.health_check).grid(row=1, column=0, padx=6, pady=6)
        ttk.Button(btns, text="One-Click Safe Bring-up", command=self.one_click_safe_bringup).grid(row=1, column=1, padx=6, pady=6, columnspan=2, sticky="we")
        ttk.Button(btns, text="Open Logs Folder", command=self.open_logs_folder).grid(row=1, column=3, padx=6, pady=6)

        ext = ttk.LabelFrame(self.root, text="External")
        ext.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(ext, text="Start SimHub", command=lambda: self._log(start_simhub())).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(ext, text="Start LFS", command=lambda: self._log(start_lfs())).grid(row=0, column=1, padx=6, pady=6)

        auto = ttk.LabelFrame(self.root, text="Autonomous Tests")
        auto.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(auto, text="test_current").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(auto, textvariable=self.test_current_var, width=10).grid(row=0, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(auto, text="spin_jv").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(auto, textvariable=self.spin_jv_var, width=10).grid(row=0, column=3, padx=6, pady=6, sticky="w")
        ttk.Label(auto, text="counts_per_rev").grid(row=0, column=4, padx=6, pady=6, sticky="w")
        ttk.Entry(auto, textvariable=self.counts_per_rev_var, width=10).grid(row=0, column=5, padx=6, pady=6, sticky="w")
        ttk.Button(auto, text="Auto Spin Verify", command=self.auto_spin_verify).grid(row=1, column=0, padx=6, pady=6)
        ttk.Button(auto, text="Rotate -1 Rev", command=lambda: self.rotate_one_rev(-1)).grid(row=1, column=1, padx=6, pady=6)
        ttk.Button(auto, text="Rotate +1 Rev", command=lambda: self.rotate_one_rev(1)).grid(row=1, column=2, padx=6, pady=6)
        ttk.Label(
            auto,
            text="These tests use the configured drive transport, read encoder position, then send a safe release sequence.",
        ).grid(row=1, column=3, columnspan=3, padx=6, pady=6, sticky="w")

        bench = ttk.LabelFrame(self.root, text="Bench Tests")
        bench.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(bench, text="current_a").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(bench, textvariable=self.bench_current_a_var, width=10).grid(row=0, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(bench, text="hold_ms").grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Entry(bench, textvariable=self.bench_hold_ms_var, width=10).grid(row=0, column=3, padx=6, pady=6, sticky="w")
        ttk.Button(bench, text="Probe All Drives", command=self.probe_all_drives).grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(bench, text="Probe Selected", command=self.probe_drive).grid(row=0, column=5, padx=6, pady=6)
        ttk.Button(bench, text="Enable Selected", command=self.enable_selected_drive).grid(row=0, column=6, padx=6, pady=6)
        ttk.Button(bench, text="Disable Selected", command=self.disable_selected_drive).grid(row=0, column=7, padx=6, pady=6)
        ttk.Button(bench, text="Zero Output", command=self.zero_selected_drive).grid(row=1, column=0, padx=6, pady=6)
        ttk.Button(bench, text="+Current Pulse", command=lambda: self.pulse_selected_drive_current(1)).grid(row=1, column=1, padx=6, pady=6)
        ttk.Button(bench, text="-Current Pulse", command=lambda: self.pulse_selected_drive_current(-1)).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(bench, text="+/- Current Pulse", command=self.bipolar_current_pulse).grid(row=1, column=3, padx=6, pady=6)
        ttk.Label(
            bench,
            text="Bench buttons target the currently selected slave index and log MO, EC, PX, mode, and status before and after each action.",
        ).grid(row=1, column=4, columnspan=4, padx=6, pady=6, sticky="w")

        pedals = ttk.LabelFrame(self.root, text="vJoy Pedals")
        pedals.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(pedals, text="Throttle").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Scale(
            pedals,
            from_=0,
            to=100,
            variable=self.throttle_var,
            orient=tk.HORIZONTAL,
            command=self._on_pedal_slider_change,
        ).grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Label(pedals, text="Brake").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Scale(
            pedals,
            from_=0,
            to=100,
            variable=self.brake_var,
            orient=tk.HORIZONTAL,
            command=self._on_pedal_slider_change,
        ).grid(row=1, column=1, padx=6, pady=6, sticky="we")
        self.throttle_label = ttk.Label(pedals, text="0%")
        self.throttle_label.grid(row=0, column=2, padx=6, pady=6, sticky="e")
        self.brake_label = ttk.Label(pedals, text="0%")
        self.brake_label.grid(row=1, column=2, padx=6, pady=6, sticky="e")
        ttk.Button(pedals, text="Reset Pedals", command=self.reset_pedals).grid(row=0, column=3, rowspan=2, padx=6, pady=6)
        pedals.columnconfigure(1, weight=1)

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
        self._log("Master GUI ready. Start Safe vJoy is steering-only. Start Adapter is the motor/FFB path.")

    def _write_vjoy_pedal_state(self, log_change: bool = True) -> None:
        throttle = float(self.throttle_var.get()) / 100.0
        brake = float(self.brake_var.get()) / 100.0
        save_input_state(throttle, brake)
        self.throttle_label.config(text=f"{int(round(self.throttle_var.get()))}%")
        self.brake_label.config(text=f"{int(round(self.brake_var.get()))}%")
        if log_change:
            self._log(
                f"vJoy pedals updated: throttle={int(round(self.throttle_var.get()))}% brake={int(round(self.brake_var.get()))}%"
            )

    def _on_pedal_slider_change(self, _value: str) -> None:
        self._write_vjoy_pedal_state(log_change=False)

    def reset_pedals(self) -> None:
        self.throttle_var.set(0.0)
        self.brake_var.set(0.0)
        self._write_vjoy_pedal_state()

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

    def _set_status(self, value: str) -> None:
        try:
            self.root.after(0, lambda: self.status_var.set(value))
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

    def _parse_last_int(self, text: str) -> int | None:
        nums = re.findall(r"-?\d+", text)
        return int(nums[-1]) if nums else None

    def _query_int(self, sp: Any, cmd: str, read_wait_s: float = 0.08) -> int | None:
        return self._parse_last_int(self._elmo_exchange(sp, cmd, read_wait_s=read_wait_s))

    def _is_ethercat(self) -> bool:
        return str(self.cfg.get("elmo_transport", "serial")).strip().lower() == "ethercat"

    def _build_client(self):
        return build_elmo_client(self.cfg)

    def _query_position(self, client: Any) -> int | None:
        try:
            return client.get_px()
        except Exception:
            return None

    def _bench_current_counts(self) -> tuple[float, int]:
        amps = float(self.bench_current_a_var.get().strip())
        counts = int(round(amps * float(self.cfg.get("current_cmd_scale", 1000.0))))
        return amps, counts

    def _bench_hold_s(self) -> tuple[int, float]:
        hold_ms = int(self.bench_hold_ms_var.get().strip())
        return hold_ms, max(0.0, hold_ms / 1000.0)

    def _log_drive_snapshot(self, client: Any, prefix: str = "") -> None:
        details = client.describe()
        label = f"{prefix} " if prefix else ""
        self._log(
            f"{label}drive snapshot: slave_index={self.cfg.get('ethercat_slave_index')} "
            f"mo={client.get_mo()} ec={client.get_ec()} px={client.get_px()} "
            f"mode_display={details.get('mode_display')} statusword={details.get('statusword')}"
        )

    def _run_bench_drive_task(self, name: str, worker: callable) -> None:
        self.stop_managed(release_after_stop=True)
        self.kill_conflicts()
        self.save_config()
        if not self._preflight_elmo_port(auto_cleanup=True):
            self._log(f"{name} aborted: drive preflight did not succeed.")
            return

        def run() -> None:
            self._set_status(f"Running: {name}")
            try:
                client = self._build_client()
                client.open()
                try:
                    self._log_drive_snapshot(client, prefix=f"{name} before")
                    worker(client)
                    self._log_drive_snapshot(client, prefix=f"{name} after")
                finally:
                    client.close()
            except Exception as exc:
                self._log(f"{name} failed: {exc}")
                self._elmo_log(f"{name} failed: {exc}")
            finally:
                self._set_status("Idle")

        threading.Thread(target=run, daemon=True).start()

    def _wait_until_stable_client(
        self,
        client: Any,
        expected_abs_delta: int,
        timeout_s: float = 8.0,
        stable_window_s: float = 0.3,
        poll_s: float = 0.06,
    ) -> tuple[int | None, int | None, int | None]:
        px0 = self._query_position(client)
        if px0 is None:
            return None, None, None

        t0 = time.time()
        reached = False
        stable_since: float | None = None
        last_px = px0

        while time.time() - t0 < timeout_s:
            px = self._query_position(client)
            if px is None:
                time.sleep(poll_s)
                continue

            delta = px - px0
            if abs(delta) >= max(1, int(expected_abs_delta * 0.90)):
                reached = True

            if px == last_px:
                if stable_since is None:
                    stable_since = time.time()
            else:
                stable_since = None
                last_px = px

            if reached and stable_since is not None and (time.time() - stable_since) >= stable_window_s:
                return px0, px, delta

            time.sleep(poll_s)

        px_end = self._query_position(client)
        return px0, px_end, (None if px_end is None else px_end - px0)

    def _wait_until_stable(
        self,
        sp: Any,
        expected_abs_delta: int,
        timeout_s: float = 8.0,
        stable_window_s: float = 0.3,
        poll_s: float = 0.06,
    ) -> tuple[int | None, int | None, int | None]:
        px0 = self._query_int(sp, "PX", read_wait_s=0.03)
        if px0 is None:
            return None, None, None

        t0 = time.time()
        reached = False
        stable_since: float | None = None
        last_px = px0

        while time.time() - t0 < timeout_s:
            px = self._query_int(sp, "PX", read_wait_s=0.03)
            if px is None:
                time.sleep(poll_s)
                continue

            delta = px - px0
            if abs(delta) >= max(1, int(expected_abs_delta * 0.90)):
                reached = True

            if px == last_px:
                if stable_since is None:
                    stable_since = time.time()
            else:
                stable_since = None
                last_px = px

            if reached and stable_since is not None and (time.time() - stable_since) >= stable_window_s:
                return px0, px, delta

            time.sleep(poll_s)

        px_end = self._query_int(sp, "PX", read_wait_s=0.03)
        return px0, px_end, (None if px_end is None else px_end - px0)

    def _run_autonomous_drive_task(self, name: str, worker: callable) -> None:
        self.stop_managed(release_after_stop=True)
        self.kill_conflicts()
        if not self._preflight_elmo_port(auto_cleanup=True):
            self._log(f"{name} aborted: drive preflight did not succeed.")
            return

        def run() -> None:
            self._set_status(f"Running: {name}")
            try:
                client = self._build_client()
                client.open()
                try:
                    worker(client)
                finally:
                    client.close()
            except Exception as exc:
                self._log(f"{name} failed: {exc}")
                self._elmo_log(f"{name} failed: {exc}")
            finally:
                self._run_release_sequence()
                self._set_status("Idle")

        threading.Thread(target=run, daemon=True).start()

    def save_config(self) -> None:
        try:
            self.cfg["elmo_transport"] = self.transport_var.get().strip().lower()
            self.cfg["sim_source"] = self.src_var.get().strip()
            self.cfg["auto_motor_on"] = bool(self.auto_on_var.get())
            self.cfg["motor_off_on_exit"] = bool(self.off_on_exit_var.get())
            self.cfg["loop_hz"] = int(self.loop_var.get().strip())
            self.cfg["px_poll_every_loops"] = int(self.px_skip_var.get().strip())
            self.cfg["ethercat_adapter_match"] = self.ethercat_adapter_var.get().strip()
            self.cfg["ethercat_slave_index"] = int(self.ethercat_slave_var.get().strip())
            self.cfg["ethercat_profile_velocity"] = int(self.ethercat_profile_velocity_var.get().strip())
            self.cfg["ethercat_profile_acceleration"] = int(self.ethercat_profile_accel_var.get().strip())
            self.cfg["ethercat_profile_deceleration"] = int(self.ethercat_profile_decel_var.get().strip())
            self.cfg["ethercat_allow_degraded_enable"] = bool(self.ethercat_degraded_enable_var.get())
            self.cfg["elmo_command_mode"] = self.cmd_mode_var.get().strip().lower()
            self.cfg["ffb_strength"] = float(self.ffb_strength_var.get().strip())
            self.cfg["max_current_a"] = float(self.max_current_a_var.get().strip())
            self.cfg["motor_current_utilization"] = float(self.motor_current_utilization_var.get().strip())
            self.cfg["min_current_a"] = float(self.min_current_a_var.get().strip())
            self.cfg["current_cmd_scale"] = float(self.current_cmd_scale_var.get().strip())
            self.cfg["max_il_step_per_loop"] = int(self.max_il_step_var.get().strip())
            self.cfg["max_pr_per_loop"] = int(self.max_pr_per_loop_var.get().strip())
            self.cfg["max_pr_step_per_loop"] = int(self.max_pr_step_var.get().strip())
            self.cfg["max_tc"] = int(self.max_tc_var.get().strip())
            self.cfg["max_tc_step_per_loop"] = int(self.max_tc_step_var.get().strip())
            self.cfg["ffb_deadband"] = int(self.ffb_deadband_var.get().strip())
            self.cfg["ffb_input_max"] = int(self.ffb_input_max_var.get().strip())
            self.cfg["vjoy_device_id"] = int(self.vjoy_device_id_var.get().strip())
            self.cfg["wheel_lock_deg"] = float(self.wheel_lock_deg_var.get().strip())
            self.cfg["ffb_fallback_to_inject"] = bool(self.inject_fallback_var.get())
            self.cfg["ffb_fallback_after_s"] = float(self.fallback_after_var.get().strip())
            self.cfg["release_motor_on_idle_ffb"] = bool(self.idle_release_var.get())
            self._save_cfg()
            self._log(
                "Config saved. "
                f"transport={self.cfg['elmo_transport']} "
                f"sim_source={self.cfg['sim_source']} "
                f"mode={self.cfg['elmo_command_mode']} "
                f"ffb_strength={self.cfg['ffb_strength']} "
                f"max_current_a={self.cfg['max_current_a']} "
                f"degraded_enable={self.cfg['ethercat_allow_degraded_enable']}"
            )
            if self.cfg["elmo_transport"] == "ethercat" and self.cfg["ethercat_allow_degraded_enable"]:
                self._log("WARN ethercat_allow_degraded_enable=true. Use this only for bench diagnostics, not normal runtime.")
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

    def _preflight_elmo_port(self, auto_cleanup: bool = True) -> bool:
        if self._is_ethercat():
            try:
                client = self._build_client()
                client.open()
                client.close()
                return True
            except Exception as exc:
                self._log(f"EtherCAT preflight failed: {exc}")
                if auto_cleanup:
                    self._log("Attempting automatic conflict cleanup for EtherCAT path.")
                    self.kill_conflicts()
                    time.sleep(0.5)
                    try:
                        client = self._build_client()
                        client.open()
                        client.close()
                        self._log("EtherCAT preflight succeeded after cleanup.")
                        return True
                    except Exception as retry_exc:
                        self._log(f"EtherCAT preflight still failed after cleanup: {retry_exc}")
                return False

        if serial is None:
            self._log("pyserial unavailable.")
            return False

        port = str(self.cfg.get("elmo_port", "COM13"))
        baud = int(self.cfg.get("elmo_baud", 115200))

        try:
            with serial.Serial(port, baud, timeout=0.1):
                pass
            return True
        except Exception as exc:
            self._log(f"Preflight {port}@{baud} failed: {exc}")
            if not auto_cleanup:
                return False

            self._log(f"Attempting automatic conflict cleanup for {port}.")
            self.kill_conflicts()
            time.sleep(0.5)

            try:
                with serial.Serial(port, baud, timeout=0.1):
                    pass
                self._log(f"Preflight {port}@{baud} succeeded after cleanup.")
                return True
            except Exception as retry_exc:
                self._log(f"Preflight still failed after cleanup: {retry_exc}")
                return False

    def health_check(self) -> None:
        port = str(self.cfg.get("elmo_port", "COM13"))
        baud = int(self.cfg.get("elmo_baud", 115200))
        ws_url = str(self.cfg.get("sim_ws_url", "ws://127.0.0.1:8888"))
        direct_vjoy = str(self.cfg.get("sim_source", "")).lower().strip() == "vjoy_ffb"
        simhub_port_ok = self._is_port_open("127.0.0.1", 8888)
        com_ok = self._can_open_serial(port, baud) if not self._is_ethercat() else self._preflight_elmo_port(auto_cleanup=False)
        if direct_vjoy:
            self._log(f"HEALTH vjoy_interface_dll={'OK' if VJOY_INTERFACE_DLL.exists() else 'MISSING'} path={VJOY_INTERFACE_DLL}")
            self._log("HEALTH simhub=NOT_REQUIRED for sim_source=vjoy_ffb")
        else:
            self._log(f"HEALTH simhub_port_8888={'OK' if simhub_port_ok else 'DOWN'}")
        if self._is_ethercat():
            self._log(
                "HEALTH ethercat="
                f"{'OK' if com_ok else 'DOWN'} "
                f"adapter_match={self.cfg.get('ethercat_adapter_match')} slave_index={self.cfg.get('ethercat_slave_index')} "
                f"degraded_enable={self.cfg.get('ethercat_allow_degraded_enable', False)}"
            )
        else:
            self._log(f"HEALTH {port}@{baud}={'OK' if com_ok else 'BUSY/DOWN'}")
        self._log(f"HEALTH sim_source={self.cfg.get('sim_source')} sim_ws_url={ws_url}")
        self._log(
            "HEALTH output_mode="
            f"{self.cfg.get('elmo_command_mode')} transport={self.cfg.get('elmo_transport')} "
            f"ffb_strength={self.cfg.get('ffb_strength')} "
            f"max_current_a={self.cfg.get('max_current_a')} "
            f"motor_current_utilization={self.cfg.get('motor_current_utilization')}"
        )

    def scan_ethercat(self) -> None:
        if not self._is_ethercat():
            self._log("Scan EtherCAT skipped: drive transport is not set to ethercat.")
            return

        def run_scan() -> None:
            try:
                infos = scan_ethercat_bus(self.cfg)
                self._log(f"EtherCAT scan found {len(infos)} slave(s).")
                for info in infos:
                    self._log(
                        f"EtherCAT slave[{info.slave_index}] name={info.device_name or info.name} "
                        f"vendor={info.vendor_id} product={info.product_code} rev={info.revision} serial={info.serial_number}"
                    )
            except Exception as exc:
                self._log(f"EtherCAT scan failed: {exc}")

        threading.Thread(target=run_scan, daemon=True).start()

    def probe_all_drives(self) -> None:
        if not self._is_ethercat():
            self._log("Probe All Drives is available only for EtherCAT transport.")
            return

        self.save_config()

        def run_probe_all() -> None:
            self._set_status("Running: probe_all_drives")
            try:
                infos = scan_ethercat_bus(self.cfg)
                self._log(f"Probe All Drives: found {len(infos)} slave(s).")
                original_slave_index = int(self.cfg.get("ethercat_slave_index", 1))
                for info in infos:
                    self.cfg["ethercat_slave_index"] = info.slave_index
                    client = self._build_client()
                    client.open()
                    try:
                        details = client.describe()
                        self._log(
                            f"slave[{info.slave_index}] serial={details.get('serial_number')} mo={client.get_mo()} ec={client.get_ec()} "
                            f"px={client.get_px()} mode={details.get('mode_display')} statusword={details.get('statusword')}"
                        )
                    finally:
                        client.close()
                self.cfg["ethercat_slave_index"] = original_slave_index
            except Exception as exc:
                self._log(f"Probe All Drives failed: {exc}")
            finally:
                self._set_status("Idle")

        threading.Thread(target=run_probe_all, daemon=True).start()

    def one_click_safe_bringup(self) -> None:
        def run() -> None:
            try:
                self._log("One-click safe bring-up starting.")
                self.save_config()
                self.kill_conflicts()
                self.health_check()
                self.release_motor()
                time.sleep(0.2)
                if self._is_direct_vjoy_ffb():
                    self._log("Skipping SimHub start because sim_source=vjoy_ffb uses direct game FFB via vJoy.")
                else:
                    self._log(start_simhub())
                time.sleep(0.2)
                self._log(start_lfs())
                self._log("One-click safe bring-up complete. Start Safe vJoy for steering-only validation, then Start Adapter for motor/FFB.")
            except Exception as exc:
                self._log(f"One-click safe bring-up failed: {exc}")

        threading.Thread(target=run, daemon=True).start()

    def open_logs_folder(self) -> None:
        try:
            os.startfile(str(LOG_DIR))
        except Exception as exc:
            self._log(f"Open logs folder failed: {exc}")

    def probe_drive(self) -> None:
        def run_probe():
            try:
                self.save_config()
                client = self._build_client()
                client.open()
                try:
                    details = client.describe()
                    for key, value in details.items():
                        self._log(f"{key} => {value}")
                    self._log(f"MO => {client.get_mo()}")
                    self._log(f"EC => {client.get_ec()}")
                    self._log(f"PX => {client.get_px()}")
                finally:
                    client.close()
            except Exception as exc:
                self._log(f"Probe failed: {exc}")
                self._elmo_log(f"Probe failed: {exc}")

        threading.Thread(target=run_probe, daemon=True).start()

    def enable_selected_drive(self) -> None:
        def worker(client: Any) -> None:
            self._log(f"Enable Selected => {client.set_motor_on()}")

        self._run_bench_drive_task("enable_selected_drive", worker)

    def disable_selected_drive(self) -> None:
        def worker(client: Any) -> None:
            try:
                self._log(f"TC0 => {client.set_tc(0)}")
            except Exception:
                pass
            try:
                self._log(f"IL0 => {client.set_il(0)}")
            except Exception:
                pass
            self._log(f"STOP => {client.stop_motion()}")
            self._log(f"MO0 => {client.set_motor_off()}")

        self._run_bench_drive_task("disable_selected_drive", worker)

    def zero_selected_drive(self) -> None:
        def worker(client: Any) -> None:
            try:
                self._log(f"TC0 => {client.set_tc(0)}")
            except Exception as exc:
                self._log(f"TC0 skipped: {exc}")
            try:
                self._log(f"IL0 => {client.set_il(0)}")
            except Exception as exc:
                self._log(f"IL0 skipped: {exc}")

        self._run_bench_drive_task("zero_selected_drive", worker)

    def pulse_selected_drive_current(self, direction: int) -> None:
        try:
            amps, counts = self._bench_current_counts()
            hold_ms, hold_s = self._bench_hold_s()
        except Exception as exc:
            messagebox.showerror("Invalid bench settings", str(exc))
            return

        signed_counts = counts if direction >= 0 else -counts
        signed_amps = amps if direction >= 0 else -amps
        task_name = "pulse_selected_drive_current_pos" if direction >= 0 else "pulse_selected_drive_current_neg"

        def worker(client: Any) -> None:
            px_before = client.get_px()
            self._log(f"MO1 => {client.set_motor_on()}")
            self._log(f"IL {signed_amps:.3f}A ({signed_counts} counts) => {client.set_il(signed_counts)}")
            time.sleep(hold_s)
            px_mid = client.get_px()
            self._log(f"IL0 => {client.set_il(0)}")
            try:
                self._log(f"STOP => {client.stop_motion()}")
            except Exception:
                pass
            px_after = client.get_px()
            delta = None if px_before is None or px_after is None else px_after - px_before
            self._log(
                f"Current pulse result: amps={signed_amps:.3f} hold_ms={hold_ms} px_before={px_before} px_mid={px_mid} px_after={px_after} delta={delta}"
            )

        self._run_bench_drive_task(task_name, worker)

    def bipolar_current_pulse(self) -> None:
        try:
            amps, counts = self._bench_current_counts()
            hold_ms, hold_s = self._bench_hold_s()
        except Exception as exc:
            messagebox.showerror("Invalid bench settings", str(exc))
            return

        def worker(client: Any) -> None:
            px_before = client.get_px()
            self._log(f"MO1 => {client.set_motor_on()}")
            self._log(f"IL +{amps:.3f}A ({counts} counts) => {client.set_il(counts)}")
            time.sleep(hold_s)
            px_mid = client.get_px()
            self._log(f"IL -{amps:.3f}A ({-counts} counts) => {client.set_il(-counts)}")
            time.sleep(hold_s)
            px_mid2 = client.get_px()
            self._log(f"IL0 => {client.set_il(0)}")
            try:
                self._log(f"STOP => {client.stop_motion()}")
            except Exception:
                pass
            px_after = client.get_px()
            delta = None if px_before is None or px_after is None else px_after - px_before
            self._log(
                f"Bipolar current pulse result: amps={amps:.3f} hold_ms={hold_ms} px_before={px_before} px_mid={px_mid} px_mid2={px_mid2} px_after={px_after} delta={delta}"
            )

        self._run_bench_drive_task("bipolar_current_pulse", worker)

    def release_motor(self) -> None:
        def run_release():
            self._run_release_sequence()

        threading.Thread(target=run_release, daemon=True).start()

    def _run_release_sequence(self) -> bool:
        try:
            client = self._build_client()
            client.open()
            try:
                self._log(f"STOP => {client.stop_motion()}")
                self._log(f"TC0 => {client.set_tc(0)}")
                self._log(f"MO0 => {client.set_motor_off()}")
                self._log(f"MO => {client.get_mo()}")
            finally:
                client.close()
            self._log("Motor release sequence done. Shaft should be disabled.")
            self._elmo_log("Release sequence done.")
            return True
        except Exception as exc:
            self._log(f"Release failed: {exc}")
            self._elmo_log(f"Release failed: {exc}")
            return False

    def _start_managed(self, args: list[str], name: str, require_drive_preflight: bool = True) -> None:
        self.stop_managed(release_after_stop=True)
        self.kill_conflicts()
        if require_drive_preflight and not self._preflight_elmo_port(auto_cleanup=True):
            self._log(f"Start {name} aborted: drive preflight did not succeed.")
            return
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
        sim_source = str(self.cfg.get("sim_source", "")).lower().strip()
        command_mode = str(self.cfg.get("elmo_command_mode", "pr")).lower().strip()
        transport = str(self.cfg.get("elmo_transport", "serial")).lower().strip()
        if str(self.cfg.get("sim_source", "")).lower() == "websocket" and not self._is_port_open("127.0.0.1", 8888):
            self._log("WARN sim_source=websocket but SimHub port 8888 is not reachable.")
        if sim_source != "vjoy_ffb":
            self._log(
                f"WARN Start Adapter is using sim_source={sim_source}. If you expect game FFB via the vJoy wheel device, switch sim_source to vjoy_ffb."
            )
        else:
            self._log(
                "Starting adapter for direct game FFB via vJoy. "
                f"transport={transport} mode={command_mode} device={self.cfg.get('vjoy_device_id')} SimHub not required."
            )
        if command_mode == "pr":
            self._log("INFO elmo_command_mode=pr uses motion-reference fallback. Current-limit fields are saved but do not directly drive output in PR mode.")
        elif command_mode == "il":
            self._log(
                "INFO elmo_command_mode=il uses current mapping. "
                f"max_current_a={self.cfg.get('max_current_a')} "
                f"motor_current_utilization={self.cfg.get('motor_current_utilization')} "
                f"min_current_a={self.cfg.get('min_current_a')}"
            )
        elif command_mode == "tc":
            self._log(f"INFO elmo_command_mode=tc will use the configured {transport} transport.")
        if transport == "ethercat" and bool(self.cfg.get("ethercat_allow_degraded_enable", False)):
            self._log("WARN EtherCAT degraded enable is active. This is bench-only behavior and should stay off for normal use.")
        if bool(self.cfg.get("release_motor_on_idle_ffb", False)):
            self._log(
                "WARN release_motor_on_idle_ffb=true. If game FFB drops near zero, the adapter will motor-off after the idle timeout and holding torque will fall away."
            )
        python_exe = str((ROOT.parent / ".venv" / "Scripts" / "python.exe").resolve())
        if not Path(python_exe).exists():
            python_exe = sys.executable
        self._start_managed([python_exe, str((ROOT / "adapter_main.py").resolve())], "adapter_main")

    def start_safe_vjoy(self) -> None:
        self._log("Starting Safe vJoy: steering on vJoy X, GUI throttle on vJoy Z, GUI brake on vJoy RZ, motor force disabled by design.")
        python_exe = str((ROOT.parent / ".venv" / "Scripts" / "python.exe").resolve())
        if not Path(python_exe).exists():
            python_exe = sys.executable
        self._start_managed(
            [python_exe, str((ROOT / "wheel_sim_bridge.py").resolve()), "--mode", "vjoy"],
            "wheel_sim_bridge_safe",
            require_drive_preflight=False,
        )

    def auto_spin_verify(self) -> None:
        try:
            tc = int(self.test_current_var.get().strip())
            jv = int(self.spin_jv_var.get().strip())
        except Exception as exc:
            messagebox.showerror("Invalid test settings", str(exc))
            return

        def worker(client: Any) -> None:
            self._log(
                f"Auto Spin Verify: transport={self.cfg.get('elmo_transport')} mode={self.cfg.get('elmo_command_mode')} test_current={tc} spin_jv={jv}"
            )
            client.set_motor_off()
            client.set_um(5)
            client.set_rm(1)
            self._log(f"MO1 => {client.set_motor_on()}")

            px_before = client.get_px()
            self._log(f"TC+ => {client.set_tc(tc)}")
            time.sleep(0.35)
            self._log(f"TC- => {client.set_tc(-tc)}")
            time.sleep(0.35)
            self._log(f"TC0 => {client.set_tc(0)}")
            time.sleep(0.08)
            px_after_torque = client.get_px()
            torque_delta = None if px_before is None or px_after_torque is None else abs(px_after_torque - px_before)
            self._log(f"Auto Spin Verify torque pulse: px_before={px_before} px_after={px_after_torque} delta={torque_delta}")

            px_before_spin = client.get_px()
            self._log(f"PR quarter-rev => {client.set_pr(int(abs(jv) * 10))}")
            self._log(f"BG => {client.begin_motion()}")
            px0, px_mid, _delta = self._wait_until_stable_client(client, expected_abs_delta=max(1000, int(abs(jv) * 8)), timeout_s=2.5)
            self._log(f"ST => {client.stop_motion()}")
            px_after_spin = client.get_px()
            spin_delta = None if px_before_spin is None or px_mid is None else abs(px_mid - px_before_spin)
            rotation_ok = bool((spin_delta is not None and spin_delta > 100) or (torque_delta is not None and torque_delta > 100))
            self._log(
                "Auto Spin Verify result: "
                f"px0={px0} px_before={px_before_spin} px_mid={px_mid} px_after={px_after_spin} spin_delta={spin_delta} rotation_ok={rotation_ok}"
            )

        self._run_autonomous_drive_task("auto_spin_verify", worker)

    def rotate_one_rev(self, direction: int) -> None:
        try:
            counts_per_rev = int(self.counts_per_rev_var.get().strip())
        except Exception as exc:
            messagebox.showerror("Invalid test settings", str(exc))
            return

        cmd_counts = counts_per_rev if direction >= 0 else -counts_per_rev
        name = "rotate_plus_one_rev" if direction >= 0 else "rotate_minus_one_rev"

        def worker(client: Any) -> None:
            self._log(f"{name}: starting autonomous move with cmd_counts={cmd_counts}")
            self._log(f"ST => {client.stop_motion()}")
            self._log(f"TC0 => {client.set_tc(0)}")
            self._log(f"MO0 => {client.set_motor_off()}")
            self._log(f"UM => {client.set_um(5)}")
            self._log(f"RM => {client.set_rm(1)}")
            self._log(f"MO1 => {client.set_motor_on()}")

            mo = client.get_mo()
            details = client.describe()
            um = details.get("mode_display")
            self._log(f"{name}: drive state MO={mo} UM={um}")

            self._log(f"PR => {client.set_pr(cmd_counts)}")
            self._log(f"BG => {client.begin_motion()}")
            px0, px1, delta = self._wait_until_stable_client(client, expected_abs_delta=counts_per_rev)
            ok = (delta is not None) and (abs(abs(delta) - counts_per_rev) <= int(counts_per_rev * 0.15))
            self._log(
                f"{name}: px0={px0} px1={px1} delta={delta} target={counts_per_rev} ok={ok}"
            )

        self._run_autonomous_drive_task(name, worker)

    def stop_managed(self, release_after_stop: bool = True) -> None:
        stopped = False
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
                stopped = True
            except Exception as exc:
                self._log(f"Stop managed failed: {exc}")
        elif self.proc_name:
            stopped = True

        if release_after_stop:
            if self._run_release_sequence():
                if stopped:
                    self._log("Managed stop completed and motor released.")
                else:
                    self._log("No managed process was running; motor release sequence still sent.")

        self.proc = None
        self.proc_name = ""
        self.status_var.set("Idle")
        self.reset_pedals()

    def on_close(self) -> None:
        self.stop_managed(release_after_stop=bool(self.cfg.get("motor_off_on_exit", True)))
        if bool(self.cfg.get("motor_off_on_exit", True)):
            self._log("Window close: motor_off_on_exit enabled, release sequence sent.")
        self.root.destroy()

    def panic_stop(self) -> None:
        self.stop_managed(release_after_stop=True)
        self.kill_conflicts()
        self._log("PANIC STOP completed.")

    def _heartbeat(self) -> None:
        if self.proc and self.proc.poll() is not None:
            code = self.proc.returncode
            self._log(f"Managed process exited with code {code}")
            if bool(self.cfg.get("motor_off_on_exit", True)):
                threading.Thread(target=self._run_release_sequence, daemon=True).start()
                self._log("Managed process exit detected; release sequence sent.")
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
