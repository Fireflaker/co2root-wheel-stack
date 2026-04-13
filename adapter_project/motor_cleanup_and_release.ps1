param(
    [string]$Port = "COM13",
    [int]$Baud = 115200
)

Write-Host "[1/3] Stopping potential controller processes..."
Get-Process | Where-Object { $_.ProcessName -match 'python|simhub|wheel_sim_bridge|LFS' } |
    ForEach-Object {
        try {
            Stop-Process -Id $_.Id -Force -ErrorAction Stop
            Write-Host "  Stopped $($_.ProcessName) PID=$($_.Id)"
        } catch {
            Write-Host "  Skip $($_.ProcessName) PID=$($_.Id): $($_.Exception.Message)"
        }
    }

Start-Sleep -Milliseconds 300

Write-Host "[2/3] Sending hard motor release sequence on $Port..."
$sp = [System.IO.Ports.SerialPort]::new($Port, $Baud)
try {
    $sp.Open()
    Start-Sleep -Milliseconds 120

    foreach ($cmd in @('ST','TC=0','MO=0','MO=0','ST','MO')) {
        $sp.WriteLine($cmd)
        Start-Sleep -Milliseconds 80
    }

    Start-Sleep -Milliseconds 120
    $resp = $sp.ReadExisting()
    Write-Host "  Readback: $resp"
} catch {
    Write-Host "  Release failed: $($_.Exception.Message)"
} finally {
    if ($sp.IsOpen) { $sp.Close() }
}

Write-Host "[3/3] Done. Motor should now be released (MO=0)."
Write-Host "      Start bridge later in SAFE mode (default) without enabling motor."
