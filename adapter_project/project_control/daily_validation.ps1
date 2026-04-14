param(
    [string]$PythonExe = "e:/Co2Root/.venv/Scripts/python.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "[1/3] Compile check..."
& $PythonExe -m py_compile "$root/master_control_gui.py" "$root/adapter_main.py"

Write-Host "[2/3] Unit tests..."
& $PythonExe -m unittest discover -s "$root/tests" -p "test_*.py"

Write-Host "[3/3] Health note..."
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$line = "- $timestamp daily_validation.ps1: compile+tests passed"
Add-Content -Path "$root/project_control/WORK_LOG.md" -Value $line

Write-Host "Validation complete."
