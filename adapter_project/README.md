# Adapter Project

This folder provides a direct, testable path from sim force input to Elmo drive output over either serial or EtherCAT.

## Files

- `adapter_main.py`: Runtime adapter loop (FFB source -> drive command -> optional vJoy).
- `config.json`: Runtime settings.
- `elmo_transport.py`: Shared serial and EtherCAT transport layer for the Elmo drive path.
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

`start_adapter.ps1` performs a drive preflight before launch.
For serial it checks COM access. For EtherCAT it attempts an adapter open against the configured slave path.
If `elmo_transport` is `ethercat`, the launcher will relaunch elevated because Windows raw EtherCAT access requires admin.

## Verify Hardware Control (Proof)

```powershell
cd e:/Co2Root/adapter_project
python ./verify_adapter_control.py --transport ethercat --ethercat-slave-index 1 --tc 140 --hold-ms 250 --json-out ./last_verify.json
```

Pass condition: `px_delta >= 100` and exit code 0. When no motor is attached, the script still validates command path, mode, and status behavior, but movement-based pass criteria may not be met.

## Use Sim Software Feed

Set source mode to one of:

- `http` -> reads SimHub game data endpoint
- `serial` -> reads integer force stream from configured COM source

Example:

```powershell
./start_adapter.ps1 -Source http

Notes:

- EtherCAT mode uses standard CiA402 objects such as `6040h`, `6041h`, `6060h`, `6061h`, `6064h`, `6071h`, and `607Ah`.
- `elmo_command_mode=pr` maps to profile position mode on the EtherCAT transport.
- `elmo_command_mode=il` and `elmo_command_mode=tc` both use torque-oriented EtherCAT writes; `tc` is the preferred FFB path.

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
