param(
    [string]$Name = "step",
    [int]$ClickX = -1,
    [int]$ClickY = -1
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class GuiApi {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@

$shotDir = Join-Path $PSScriptRoot "screenshots"
New-Item -ItemType Directory -Force -Path $shotDir | Out-Null

function Save-Shot([string]$path) {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose()
    $bmp.Dispose()
}

$sim = Get-Process | Where-Object { $_.MainWindowTitle -like "*SimHub*" } | Select-Object -First 1
if ($sim) {
    [GuiApi]::SetForegroundWindow($sim.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 200
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$before = Join-Path $shotDir ("gui_" + $ts + "_" + $Name + "_before.png")
$after = Join-Path $shotDir ("gui_" + $ts + "_" + $Name + "_after.png")
Save-Shot $before

if ($ClickX -ge 0 -and $ClickY -ge 0) {
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($ClickX, $ClickY)
    Start-Sleep -Milliseconds 120
    [GuiApi]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 40
    [GuiApi]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

Start-Sleep -Milliseconds 250
Save-Shot $after
Write-Host "Saved: $before"
Write-Host "Saved: $after"
