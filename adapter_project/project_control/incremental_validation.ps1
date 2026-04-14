param(
    [ValidateSet("compile", "unit", "full")]
    [string]$Stage = "full",
    [string]$PythonExe = "e:/Co2Root/.venv/Scripts/python.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Invoke-CompileChecks {
    Write-Host "[compile] Checking Python compile targets..."
    & $PythonExe -m py_compile `
        "$root/adapter_main.py" `
        "$root/master_control_gui.py" `
        "$root/wheel_sim_bridge.py"
}

function Invoke-UnitTests {
    Write-Host "[unit] Running unit tests..."
    & $PythonExe -m unittest discover -s "$root/tests" -p "test_*.py"
}

if ($Stage -eq "compile") {
    Invoke-CompileChecks
}
elseif ($Stage -eq "unit") {
    Invoke-UnitTests
}
else {
    Invoke-CompileChecks
    Invoke-UnitTests
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$line = "- $timestamp incremental_validation.ps1 stage=${Stage}: passed"
Add-Content -Path "$root/project_control/WORK_LOG.md" -Value $line

Write-Host "Incremental validation complete for stage=$Stage"
