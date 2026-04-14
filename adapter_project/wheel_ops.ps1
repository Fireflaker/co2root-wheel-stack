param(
    [ValidateSet('status','release','start-vjoy','start-udp','stop-all')]
    [string]$Action = 'status',
    [string]$Port = 'COM13',
    [int]$Baud = 115200
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py = Join-Path $Root '..\.venv\Scripts\python.exe'
if (!(Test-Path $Py)) { $Py = 'python' }

function Invoke-Release {
    param([string]$PortName, [int]$BaudRate)
    $sp = [System.IO.Ports.SerialPort]::new($PortName, $BaudRate)
    try {
        $sp.Open()
        Start-Sleep -Milliseconds 120
        foreach ($cmd in @('ST','TC=0','MO=0','MO=0','ST','MO')) {
            $sp.WriteLine($cmd)
            Start-Sleep -Milliseconds 80
        }
        Start-Sleep -Milliseconds 120
        $resp = $sp.ReadExisting()
        Write-Host "Release sequence sent. Readback: $resp"
    } catch {
        Write-Host "Release error: $($_.Exception.Message)"
    } finally {
        if ($sp.IsOpen) { $sp.Close() }
    }
}

switch ($Action) {
    'status' {
        Write-Host 'Processes:'
        Get-Process | Where-Object { $_.ProcessName -match 'python|LFS|simhub|vjoy' } |
            Select-Object ProcessName, Id | Sort-Object ProcessName | Format-Table -AutoSize
        Write-Host 'Ports:'
        [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object | ForEach-Object { Write-Host "  $_" }
    }
    'release' {
        Invoke-Release -PortName $Port -BaudRate $Baud
    }
    'stop-all' {
        Get-Process | Where-Object { $_.ProcessName -match 'python|simhub|LFS' } |
            ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 300
        Invoke-Release -PortName $Port -BaudRate $Baud
        Write-Host 'Stopped all known holders and sent release.'
    }
    'start-vjoy' {
        Write-Host 'Starting SAFE vJoy bridge (MotorEnable=False)...'
        & $Py (Join-Path $Root 'wheel_sim_bridge.py') --mode vjoy
    }
    'start-udp' {
        Write-Host 'Starting SAFE UDP bridge (MotorEnable=False)...'
        & $Py (Join-Path $Root 'wheel_sim_bridge.py') --mode udp
    }
}
