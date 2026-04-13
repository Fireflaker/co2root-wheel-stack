$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (Test-Path $venvPy) {
    & $venvPy (Join-Path $PSScriptRoot 'master_control_gui.py')
} else {
    python (Join-Path $PSScriptRoot 'master_control_gui.py')
}
