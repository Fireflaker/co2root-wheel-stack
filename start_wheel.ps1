param(
    [string]$WorkspaceRoot = "e:/Co2Root",
    [string]$BridgeElmoPort = "",
    [ValidateSet("websocket", "http", "serial", "inject")]
    [string]$FfbSource = "websocket",
    [string]$BridgeSimHubPort = "COM11",
    [string]$BridgeSimHubWsUrl = "ws://127.0.0.1:8888",
    [string]$BridgeSimHubHttpUrl = "http://127.0.0.1:8888/api/GetGameData",
    [switch]$SkipSimHub,
    [switch]$RunInForeground,
    [switch]$SkipConfigure
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red }

function Get-PythonExe {
    $venvPy = Join-Path $WorkspaceRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    return "python"
}

function Start-SimHub {
    if ($SkipSimHub) {
        Write-Step "Skipping SimHub launch per flag"
        return
    }

    $candidates = @(
        "C:\Program Files\SimHub\SimHubWPF.exe",
        "C:\Program Files (x86)\SimHub\SimHubWPF.exe",
        (Join-Path $WorkspaceRoot "SimHub\SimHubWPF.exe")
    )

    $exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $exe) {
        Write-Step "SimHub executable not found, continuing without SimHub"
        return
    }

    Write-Step "Starting SimHub"
    Start-Process -FilePath $exe -WindowStyle Minimized
    Start-Sleep -Seconds 4
    Write-Ok "SimHub launched"
}

function Invoke-ElmoConfigure {
    if ($SkipConfigure) {
        Write-Step "Skipping Elmo configure/verify per flag"
        return
    }

    $python = Get-PythonExe
    $cfg = Join-Path $WorkspaceRoot "elmo_configure.py"

    if (-not (Test-Path $cfg)) {
        throw "elmo_configure.py not found at $cfg"
    }

    $verifyArgs = @($cfg, "--verify-only")
    if ($BridgeElmoPort) {
        $verifyArgs += @("--port", $BridgeElmoPort)
    }

    Write-Step "Verifying Elmo config"
    & $python @verifyArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Step "Verify failed, applying full configure"
        $fullArgs = @($cfg)
        if ($BridgeElmoPort) {
            $fullArgs += @("--port", $BridgeElmoPort)
        }
        & $python @fullArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to configure Elmo"
        }
    }
    Write-Ok "Elmo config verified"
}

function Start-Bridge {
    $bridge = Join-Path $WorkspaceRoot "elmo_ffb_bridge.py"
    if (-not (Test-Path $bridge)) {
        throw "Bridge script not found: $bridge"
    }

    $python = Get-PythonExe

    if ($BridgeElmoPort) {
        Set-Item -Path Env:ELMO_PORT -Value $BridgeElmoPort
    }
    Set-Item -Path Env:FFB_SOURCE -Value $FfbSource
    Set-Item -Path Env:SIMHUB_PORT -Value $BridgeSimHubPort
    Set-Item -Path Env:SIMHUB_WS_URL -Value $BridgeSimHubWsUrl
    Set-Item -Path Env:SIMHUB_HTTP_URL -Value $BridgeSimHubHttpUrl

    if ($RunInForeground) {
        Write-Step "Starting bridge in foreground"
        & $python $bridge
        return
    }

    Write-Step "Starting bridge in background"
    $p = Start-Process -FilePath $python -ArgumentList @($bridge) -PassThru -WindowStyle Normal
    Write-Ok "Bridge started PID=$($p.Id)"
}

try {
    Write-Step "Starting wheel chain"
    Write-Step "FFB source mode: $FfbSource"
    Invoke-ElmoConfigure
    Start-SimHub
    Start-Bridge
    Write-Ok "Wheel chain started"
}
catch {
    Write-Fail $_
    exit 1
}
