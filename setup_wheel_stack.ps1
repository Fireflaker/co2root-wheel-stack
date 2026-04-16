param(
    [string]$WorkspaceRoot = "e:/Co2Root",
    [string]$Com0ComA = "COM10",
    [string]$Com0ComB = "COM11",
    [ValidateSet("websocket", "http", "serial", "vjoy_ffb")]
    [string]$FfbSource = "websocket",
    [switch]$SkipInstall,
    [switch]$VerboseMode
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "[STEP] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-WarnX($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red }

function Ensure-Directory($path) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

function Get-PythonExe {
    $venv = Join-Path $WorkspaceRoot ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }

    $parentVenv = Join-Path (Split-Path $WorkspaceRoot -Parent) ".venv\Scripts\python.exe"
    if (Test-Path $parentVenv) { return $parentVenv }

    return "python"
}

function Install-PythonDeps {
    Write-Step "Ensuring Python dependencies"
    $python = Get-PythonExe
    & $python -m pip install --disable-pip-version-check pyserial pyvjoy pysoem requests websocket-client | Out-Host
    Write-Ok "Python dependencies ready"
}

function Test-VJoyPresence {
    $candidatePaths = @(
        "C:\Program Files\vJoy\x64\vJoyInterface.dll",
        "C:\Program Files (x86)\vJoy\x64\vJoyInterface.dll"
    )

    foreach ($p in $candidatePaths) {
        if (Test-Path $p) { return $true }
    }
    return $false
}

function Ensure-Com0ComPair {
    Write-Step "Checking com0com pair $Com0ComA <-> $Com0ComB"

    $ports = [System.IO.Ports.SerialPort]::GetPortNames()
    $hasA = $ports -contains $Com0ComA
    $hasB = $ports -contains $Com0ComB

    if ($hasA -and $hasB) {
        Write-Ok "com0com pair already present"
        return
    }

    if ($SkipInstall) {
        throw "com0com pair $Com0ComA <-> $Com0ComB is not present and -SkipInstall forbids creating it"
    }

    $setupcPaths = @(
        "C:\Program Files (x86)\com0com\setupc.exe",
        "C:\Program Files\com0com\setupc.exe"
    )

    $setupc = $setupcPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $setupc) {

        $installerDir = Join-Path $WorkspaceRoot "installers"
        Ensure-Directory $installerDir
        $installerPath = Join-Path $installerDir "com0com-setup.exe"

        if (-not (Test-Path $installerPath)) {
            Write-Step "Downloading com0com installer"
            Invoke-WebRequest -Uri "https://sourceforge.net/projects/com0com/files/latest/download" -OutFile $installerPath
        }

        Write-Step "Installing com0com silently"
        Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait

        $setupc = $setupcPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $setupc) {
            throw "com0com install finished but setupc.exe not found"
        }
    }

    Write-Step "Creating com0com pair via setupc"
    & $setupc install PortName=$Com0ComA PortName=$Com0ComB | Out-Host

    Start-Sleep -Seconds 1
    $ports = [System.IO.Ports.SerialPort]::GetPortNames()
    $hasA = $ports -contains $Com0ComA
    $hasB = $ports -contains $Com0ComB

    if (-not ($hasA -and $hasB)) {
        Write-WarnX "Pair not visible yet via WMI. This can happen until a reboot; setupc output above is authoritative."
    } else {
        Write-Ok "com0com pair created"
    }
}

function Ensure-SimHubInstalled {
    Write-Step "Checking SimHub install"

    $simhubExeCandidates = @(
        "C:\Program Files\SimHub\SimHubWPF.exe",
        "C:\Program Files (x86)\SimHub\SimHubWPF.exe",
        (Join-Path $WorkspaceRoot "SimHub\SimHubWPF.exe")
    )

    $existing = $simhubExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($existing) {
        Write-Ok "SimHub present: $existing"
        return
    }

    if ($SkipInstall) {
        throw "SimHub not installed and -SkipInstall was provided"
    }

    $installerDir = Join-Path $WorkspaceRoot "installers"
    Ensure-Directory $installerDir

    $bundledInstaller = Join-Path $WorkspaceRoot "SimHub\SimHubSetup_9.11.10.exe"
    $installerPath = Join-Path $installerDir "SimHubSetup_9.11.10.exe"

    if (Test-Path $bundledInstaller) {
        Copy-Item $bundledInstaller $installerPath -Force
    }

    if (-not (Test-Path $installerPath)) {
        Write-WarnX "SimHub installer not found in workspace. Put installer at $installerPath or install SimHub manually later."
        return
    }

    Write-Step "Installing SimHub silently"
    Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait

    $existing = $simhubExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $existing) {
        Write-WarnX "SimHub install completed but executable not found at expected paths"
    } else {
        Write-Ok "SimHub installed"
    }
}

function Test-NpcapPresence {
    $dllCandidates = @(
        "C:\Windows\System32\Npcap\wpcap.dll",
        "C:\Windows\System32\wpcap.dll"
    )

    foreach ($candidate in $dllCandidates) {
        if (Test-Path $candidate) {
            return $true
        }
    }

    return $false
}

function Write-SimHubTemplate {
    Write-Step "Writing SimHub custom serial template"

    $cfgDir = Join-Path $env:APPDATA "SimHub\PluginsData"
    Ensure-Directory $cfgDir

    $cfgPath = Join-Path $cfgDir "SimHub.CustomSerial.Settings.json"

    $json = @{
        Port = $Com0ComA
        BaudRate = 115200
        Enabled = $true
        Formula = '$[ffb]$'
    } | ConvertTo-Json -Depth 4

    Set-Content -Path $cfgPath -Value $json -Encoding ASCII
    Write-Ok "Wrote $cfgPath"
}

function Main {
    Write-Step "Workspace root: $WorkspaceRoot"
    Write-Step "FFB source mode: $FfbSource"

    if (-not (Test-VJoyPresence)) {
        Write-WarnX "vJoy runtime not detected. Bridge may fail until vJoy is installed/enabled."
    } else {
        Write-Ok "vJoy runtime detected"
    }

    Install-PythonDeps

    if ($FfbSource -eq "serial") {
        Ensure-Com0ComPair
    } else {
        Write-Ok "Selected FFB source does not require com0com"
    }

    Ensure-SimHubInstalled

    if (Test-NpcapPresence) {
        Write-Ok "Npcap runtime detected for EtherCAT path"
    } else {
        Write-WarnX "Npcap runtime not detected. EtherCAT transport will not work until Npcap is installed."
    }

    if ($FfbSource -eq "serial") {
        Write-SimHubTemplate
    }

    Write-Host ""
    Write-Ok "Stack setup completed"
}

try {
    Main
}
catch {
    Write-Fail $_
    exit 1
}
