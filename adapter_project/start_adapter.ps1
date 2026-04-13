param(
    [ValidateSet("inject", "http", "serial", "websocket")]
    [string]$Source = "websocket",
    [switch]$SkipPortPreflight,
    [switch]$BypassMasterWarning
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

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

$venvActivate = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv/Scripts/Activate.ps1"
if (Test-Path $venvActivate) {
    . $venvActivate
}

$configPath = Join-Path $PSScriptRoot "config.json"
if (-not (Test-Path $configPath)) {
    throw "Missing config file: $configPath"
}

# Patch only sim_source for this run while preserving all other settings.
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$config.sim_source = $Source
$config | ConvertTo-Json -Depth 6 | Set-Content $configPath -Encoding ascii

$elmoPort = [string]$config.elmo_port
$elmoBaud = [int]$config.elmo_baud

if (-not $SkipPortPreflight) {
    try {
        $probe = New-Object System.IO.Ports.SerialPort $elmoPort, $elmoBaud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
        $probe.ReadTimeout = 250
        $probe.WriteTimeout = 250
        $probe.Open()
        $probe.Close()
    }
    catch {
        throw "COM port preflight failed for $elmoPort. Close demo -UseElmo, EAS, or any process holding the port. Original error: $($_.Exception.Message)"
    }
}

Write-Host "Starting adapter with source: $Source (elmo_port=$elmoPort)"
python "$PSScriptRoot/adapter_main.py"
