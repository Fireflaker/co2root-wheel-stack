# Co2Root Wheel Stack

Focused export of the direct-drive wheel control stack from the larger Co2Root workspace.

## Included

- `adapter_project/` - primary runtime, GUI, tests, and runbooks
- `start_wheel.ps1` - top-level launcher
- `setup_wheel_stack.ps1` - setup/bootstrap helper
- `elmo_ffb_bridge.py` - legacy bridge path retained for reference
- `WHEEL_TO_GAME_SETUP.md` - end-to-end setup notes

## Current validated state

- EtherCAT transport support is wired into the main adapter and master GUI
- Current checked-in config defaults to EtherCAT slave 1 on the Realtek USB 2.5GbE adapter
- Live EtherCAT validation previously confirmed 4 Elmo Whistle slaves on the bus
- The new transport uses standard CiA402 objects for mode, controlword, target torque, and target position
- `adapter_project/config.json` is set to `sim_source = websocket`
- SimHub telemetry endpoint expected at `127.0.0.1:8888`
- LFS is the fastest validated target for end-to-end bring-up
- EtherCAT on Windows requires elevation because raw packet access is used through Npcap/WinPcap-compatible APIs

## Recommended bring-up

```powershell
powershell -ExecutionPolicy Bypass -File .\adapter_project\start_master_gui.ps1
```

Then follow:

1. Kill Conflicts
2. Probe Drive
3. Start Safe vJoy
4. Start Adapter

## Notes

- This export intentionally excludes logs, screenshots, downloads, caches, and unrelated workspace content.
- The surrounding workspace contains other projects and large binary artifacts that are not part of this repo.
- If `elmo_transport` is `ethercat`, the GUI launcher will relaunch itself elevated.