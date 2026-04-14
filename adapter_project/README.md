# Adapter Project

This folder provides a direct, testable path from sim force input to Elmo command output on COM13.

## Files

- `adapter_main.py`: Runtime adapter loop (FFB source -> PR/TC command -> optional vJoy).
- `config.json`: Runtime settings.
- `start_adapter.ps1`: Single command launcher with selectable source mode.
- `verify_adapter_control.py`: Direct hardware verification pulse test.
- `gui_checkpoint.ps1`: Screenshot + optional click helper for live UI checkpoints.

## Quick Start

1. Start the adapter in inject mode. The launcher will now try to free COM13 automatically if a known holder is found.
2. Start adapter in inject mode:

```powershell
cd e:/Co2Root/adapter_project
./start_adapter.ps1 -Source inject
```

Inject mode creates clear motor movement without depending on game telemetry.

`start_adapter.ps1` performs a COM13 preflight open/close before launch.
If preflight fails, it now attempts to stop known holder processes such as adapter/demo Python runs, related PowerShell launchers, and EAS/Composer windows, then retries the preflight once.
Use `-SkipPortConflictCleanup` if you want the old fail-fast behavior without automatic cleanup.

## Verify Hardware Control (Proof)

```powershell
cd e:/Co2Root/adapter_project
python ./verify_adapter_control.py --port COM13 --tc 140 --hold-ms 250 --json-out ./last_verify.json
```

Pass condition: `px_delta >= 100` and exit code 0.

## Use Sim Software Feed

Set source mode to one of:

- `http` -> reads SimHub game data endpoint
- `serial` -> reads integer force stream from configured COM source

Example:

```powershell
./start_adapter.ps1 -Source http

Note: on current COM13 firmware in this repo, PR mode is the validated runtime path (`elmo_command_mode: "pr"`).

## Runtime Telemetry

Status logs now include:

- `loop_ms`: measured elapsed loop time
- `px_ms`: duration of PX read when polled
- `px_hz`: effective PX polling rate over the current log window
- `px_age_ms`: age of last successful PX sample
- `overrun`: percent of loops exceeding configured period

Tune via config:

- `status_log_every_s`: status print cadence (default `0.2`)
- `px_poll_every_loops`: PX polling cadence relative to loop rate (default `10`)
```

## GUI Checkpoints (single monitor)

Take before/after screenshot and click specific screen coordinate:

```powershell
./gui_checkpoint.ps1 -Name add_device -ClickX 1016 -ClickY 249
```

Screenshots are saved in `adapter_project/screenshots`.
