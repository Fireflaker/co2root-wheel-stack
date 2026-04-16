$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$configPath = Join-Path $PSScriptRoot 'config.json'
if (Test-Path $configPath) {
    $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
    if (($cfg.elmo_transport -eq 'ethercat') -and -not (Test-IsAdmin)) {
        Start-Process powershell -Verb RunAs -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
        exit 0
    }
}

$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (Test-Path $venvPy) {
    & $venvPy (Join-Path $PSScriptRoot 'master_control_gui.py')
} else {
    python (Join-Path $PSScriptRoot 'master_control_gui.py')
}
