# Wheel Safety Runbook (Streamlined)

## What was wrong
- Bridge/test scripts were enabling motor output (`MO=1`) while being used only for encoder readback.
- If a bridge stayed running, the shaft could feel hard-locked.

## Permanent fix applied
- `wheel_sim_bridge.py` now defaults to safe mode: motor remains disabled.
- Motor enable is now explicit only via `--enable-motor`.
- Added `wheel_ops.ps1` for one-command ops.

## Daily commands

### 1) Emergency release now
```powershell
powershell -ExecutionPolicy Bypass -File .\wheel_ops.ps1 -Action stop-all
```

### 2) Start bridge for LFS (safe)
```powershell
powershell -ExecutionPolicy Bypass -File .\wheel_ops.ps1 -Action start-vjoy
```

### 3) Check status
```powershell
powershell -ExecutionPolicy Bypass -File .\wheel_ops.ps1 -Action status
```

## LFS sequence (safe)
1. Run `stop-all` once before entering game.
2. Start LFS.
3. Run `start-vjoy` in another terminal.
4. In LFS Controls: bind steering to vJoy axis.
5. Keep keyboard for throttle/brake for now.

## If shaft feels locked again
1. Exit race session/menu.
2. Run `stop-all`.
3. Confirm shaft freedom by hand.
4. Restart only `start-vjoy` (safe mode).

## Notes
- Safe bridge mode reads `PX` without forcing torque.
- Do not use old scripts that set `MO=1` unless intentionally testing active torque behavior.
