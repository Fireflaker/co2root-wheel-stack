param(
    [ValidateSet("inject", "http", "serial", "websocket", "vjoy_ffb")]
    [string]$Source = "websocket",
    [switch]$SkipPortPreflight,
    [switch]$SkipPortConflictCleanup,
    [switch]$BypassMasterWarning
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PythonExe {
    $localVenv = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\python.exe"
    if (Test-Path $localVenv) {
        return $localVenv
    }

    $parentVenv = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) ".venv\Scripts\python.exe"
    if (Test-Path $parentVenv) {
        return $parentVenv
    }

    return "python"
}

function Test-MasterGuiRunning {
    $name = "Global\Co2Root_MasterControlGUI"
    try {
        $m = [System.Threading.Mutex]::OpenExisting($name)
        if ($m) {
            $m.Dispose()
            return $true
        }
        return $false
    } catch {
        return $false
    }
}

if (Test-MasterGuiRunning) {
    throw "Master Control GUI is running. Use the GUI for process control, or close it before running this legacy launcher."
}

if (-not $BypassMasterWarning) {
    Write-Warning "Legacy launcher path in use. Preferred entrypoint: .\start_master_gui.ps1"
}

function Stop-PortConflictProcesses {
    param([string]$PortName)

    $killed = New-Object System.Collections.Generic.List[string]

    $pythonCmdPattern = 'adapter_project[/\\]adapter_main\.py|wheel_sim_bridge\.py|elmo_ffb_bridge\.py|verify_adapter_control\.py|spin_and_ffb_verify\.py|direct_rotation_sweep\.py|il_pulse_verify\.py|tc_diagnostics\.py|torque_path_sweep\.py|motion_ref_discovery\.py|um_tc_discovery\.py|wheel_poller_1khz(?:_fast)?\.py|encoder_roundtrip_loop(?:_v2)?\.py|start_wheel_bridge\.py|local_screen_setup[/\\]wheel_spin_demo\.py'
    $powershellCmdPattern = 'run_wheel_demo\.ps1|run_adapter_with_demo\.ps1|motor_cleanup_and_release\.ps1|wheel_ops\.ps1|start_adapter\.ps1|start_master_gui\.ps1'
    $titlePattern = 'Elmo Application Studio|\bEAS\b|Composer'

    $pythonProcs = Get-CimInstance Win32_Process -Filter "name='python.exe' OR name='pythonw.exe'" |
        Where-Object { $_.CommandLine -match $pythonCmdPattern }

    foreach ($proc in $pythonProcs) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            $killed.Add("python PID=$($proc.ProcessId)")
        } catch {
            Write-Warning "Failed to stop python PID=$($proc.ProcessId): $($_.Exception.Message)"
        }
    }

    $psProcs = Get-CimInstance Win32_Process -Filter "name='powershell.exe' OR name='pwsh.exe'" |
        Where-Object { $_.CommandLine -match $powershellCmdPattern }

    foreach ($proc in $psProcs) {
        if ($proc.ProcessId -eq $PID) {
            continue
        }
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            $killed.Add("powershell PID=$($proc.ProcessId)")
        } catch {
            Write-Warning "Failed to stop powershell PID=$($proc.ProcessId): $($_.Exception.Message)"
        }
    }

    $windowedProcs = Get-Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.MainWindowTitle -match $titlePattern -or
            $_.ProcessName -match 'StudioManager|Composer|EAS'
        }

    foreach ($proc in $windowedProcs) {
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            $killed.Add("$($proc.ProcessName) PID=$($proc.Id)")
        } catch {
            Write-Warning "Failed to stop $($proc.ProcessName) PID=$($proc.Id): $($_.Exception.Message)"
        }
    }

    if ($killed.Count -eq 0) {
        Write-Warning "No known $PortName holder process was identified for cleanup."
    } else {
        Write-Warning "Stopped potential $PortName holders: $($killed -join ', ')"
    }
}

function Test-ElmoPortPreflight {
    param([string]$PortName, [int]$BaudRate)

    $probe = New-Object System.IO.Ports.SerialPort $PortName, $BaudRate, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
    try {
        $probe.ReadTimeout = 250
        $probe.WriteTimeout = 250
        $probe.Open()
    } finally {
        if ($probe.IsOpen) {
            $probe.Close()
        }
        $probe.Dispose()
    }
}

function Test-EthercatPreflight {
    param([string]$PythonExe, [string]$ConfigPath)

    $script = @'
from pathlib import Path
import json
import sys

config_path = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(config_path.parent))

from elmo_transport import build_elmo_client

cfg = json.loads(config_path.read_text(encoding="utf-8"))
client = build_elmo_client(cfg)
client.open()
try:
    print(client.describe())
finally:
    client.close()
'@

    $null = $script | & $PythonExe - $ConfigPath
}

$venvActivate = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv/Scripts/Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$pythonExe = Get-PythonExe

$configPath = Join-Path $PSScriptRoot "config.json"
if (-not (Test-Path $configPath)) {
    throw "Missing config file: $configPath"
}

$config = Get-Content $configPath -Raw | ConvertFrom-Json
$transport = [string]$config.elmo_transport

if (($transport -eq 'ethercat') -and -not (Test-IsAdmin)) {
    Start-Process powershell -Verb RunAs -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-Source', $Source, '-BypassMasterWarning')
    exit 0
}

$elmoPort = [string]$config.elmo_port
$elmoBaud = [int]$config.elmo_baud

if (($transport -eq 'serial') -and -not $SkipPortPreflight) {
    try {
        Test-ElmoPortPreflight -PortName $elmoPort -BaudRate $elmoBaud
    }
    catch {
        if ($SkipPortConflictCleanup) {
            throw "COM port preflight failed for $elmoPort and automatic cleanup is disabled. Original error: $($_.Exception.Message)"
        }

        Write-Warning "COM port preflight failed for $elmoPort. Attempting automatic conflict cleanup. Original error: $($_.Exception.Message)"
        Stop-PortConflictProcesses -PortName $elmoPort
        Start-Sleep -Milliseconds 500

        try {
            Test-ElmoPortPreflight -PortName $elmoPort -BaudRate $elmoBaud
            Write-Warning "$elmoPort preflight succeeded after automatic cleanup."
        }
        catch {
            throw "COM port preflight failed for $elmoPort even after automatic cleanup. Close EAS or any unknown holder, or rerun with -SkipPortConflictCleanup if you only want fail-fast behavior. Original error: $($_.Exception.Message)"
        }
    }
} elseif ($transport -eq 'ethercat') {
    try {
        Test-EthercatPreflight -PythonExe $pythonExe -ConfigPath $configPath
    }
    catch {
        throw "EtherCAT preflight failed for adapter '$($config.ethercat_adapter_match)' slave index $($config.ethercat_slave_index). Original error: $($_.Exception.Message)"
    }
}

Write-Host "Starting adapter with source: $Source (transport=$transport elmo_port=$elmoPort)"
& $pythonExe "$PSScriptRoot/adapter_main.py" --sim-source $Source
