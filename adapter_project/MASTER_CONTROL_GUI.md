# Master Control GUI

Single entry point for the wheel toolchain. Use this instead of launching multiple scripts directly.

## Launch

```powershell
powershell -ExecutionPolicy Bypass -File .\adapter_project\start_master_gui.ps1
```

Legacy launcher behavior:

- `.\adapter_project\start_adapter.ps1` is now treated as legacy.
- It defaults to `websocket` source.
- It warns to use the master GUI.
- It refuses to start if the master GUI mutex is active.

## Safety Model

- One GUI instance only (global mutex lock).
- One managed bridge process only at a time.
- `PANIC STOP` performs:
  1. stop managed process
  2. kill conflicting bridge scripts
  3. send release sequence (`ST`, `TC=0`, `MO=0`)
- Window close honors `motor_off_on_exit` and can send release sequence automatically.
- Managed process stop path is deterministic: `CTRL_BREAK_EVENT -> terminate -> kill`.

## Recommended Bring-up Sequence

1. Open GUI.
2. Click `Kill Conflicts`.
3. Click `Probe Drive` and verify responses for `MO/EC/UM/PX`.
4. Set `sim_source` to `vjoy_ffb` if the game should drive force feedback directly through vJoy.
5. Choose `elmo_command_mode`:
  - `il` to map game FFB into Elmo current commands using the GUI current-limit fields
  - `pr` to keep the proven motion-reference fallback path
  - `tc` only for experiments; this hardware has previously rejected TC commands
6. For steering-only validation: click `Start Safe vJoy`.
7. Start LFS from the GUI.
8. In LFS, map steering to `vJoy X`, throttle to `vJoy Z`, and brake to `vJoy RZ`, enable force feedback in `Options -> Controls -> Axes / FF`, then verify indicator movement.
9. Only after steering is stable, test `Start Adapter`.

When `sim_source=vjoy_ffb`, SimHub is not required for the force path.
Use SimHub only for workflows that still depend on its websocket/telemetry layer.

Alternative:

1. Click `One-Click Safe Bring-up`.
2. Then run `Start Safe vJoy` for steering validation.
3. Then run `Start Adapter` for full loop.

`One-Click Safe Bring-up` skips SimHub automatically when `sim_source=vjoy_ffb`.

## Health and Logs

- `Health Check` validates:
  - vJoy DLL presence when `sim_source=vjoy_ffb`
  - SimHub reachability on `127.0.0.1:8888` for websocket-based paths
  - Elmo serial openability on configured COM/baud
  - current sim source, output mode, and force/current settings summary
- Session logs are persisted under `adapter_project/logs/master_gui`.
- Use `Open Logs Folder` to inspect session traces quickly.

## FFB And Output Mapping

- The GUI now exposes the main FFB and output-path settings directly:
  - `elmo_command_mode`
  - `ffb_strength`, `ffb_deadband`, `ffb_input_max`
  - `max_current_a`, `motor_current_utilization`, `min_current_a`, `current_cmd_scale`
  - `max_il_step_per_loop`, `max_pr_per_loop`, `max_pr_step_per_loop`
  - `max_tc`, `max_tc_step_per_loop`
  - `vjoy_device_id`, `wheel_lock_deg`
  - `ffb_fallback_to_inject`, `ffb_fallback_after_s`, `release_motor_on_idle_ffb`
- `il` mode is the current-driven path. Those current-related settings matter there.
- `pr` mode ignores the current mapping for runtime output and instead uses position-reference fallback.
- `tc` is still exposed, but current hardware findings indicate it is not a reliable production path.

## GUI Pedals

- The GUI exposes basic `Throttle` and `Brake` sliders.
- `Start Safe vJoy` publishes steering on `vJoy X`, throttle on `vJoy Z`, and brake on `vJoy RZ`.
- `Start Adapter` also mirrors the same GUI pedal sliders onto `vJoy Z` and `vJoy RZ`.
- `Reset Pedals` returns both sliders to zero.

## Autonomous Tests

- The GUI now exposes direct hands-off motion tests for the Elmo drive.
- `Auto Spin Verify` performs a `TC` pulse attempt, then a `JV/BG` spin, and logs encoder deltas from `PX`.
- `Rotate -1 Rev` and `Rotate +1 Rev` command one full revolution using `PR/BG` in `UM=5`, then validate the encoder delta.
- `test_current`, `spin_jv`, and `counts_per_rev` are editable from the GUI before running those tests.
- Each autonomous test stops any managed bridge process first, preflights `COM13`, and finishes with `ST`, `TC=0`, and `MO=0`.

## Test Commands

```powershell
e:/Co2Root/.venv/Scripts/python.exe -m py_compile .\adapter_project\master_control_gui.py .\adapter_project\adapter_main.py .\adapter_project\wheel_sim_bridge.py
e:/Co2Root/.venv/Scripts/python.exe -m unittest discover -s .\adapter_project\tests -p "test_*.py"
powershell -ExecutionPolicy Bypass -File .\adapter_project\project_control\incremental_validation.ps1 -Stage compile
powershell -ExecutionPolicy Bypass -File .\adapter_project\project_control\incremental_validation.ps1 -Stage unit
powershell -ExecutionPolicy Bypass -File .\adapter_project\project_control\incremental_validation.ps1 -Stage full
```

## Delivery Control Docs

- Timeline: `adapter_project/project_control/WEEK_EXECUTION_PLAN.md`
- Detailed TODO: `adapter_project/project_control/DETAILED_TODO_LIST.md`
- Research backlog: `adapter_project/project_control/RESEARCH_LIST.md`
- Manual integration checklist: `adapter_project/project_control/MASTER_GUI_MANUAL_CHECKLIST.md`
- Increment completion summary: `adapter_project/project_control/INCREMENT_COMPLETION_SUMMARY.md`
- Next increment backlog: `adapter_project/project_control/NEXT_INCREMENT_BACKLOG.md`
- Branching: `adapter_project/project_control/BRANCH_STRATEGY.md`
- Decisions: `adapter_project/project_control/DECISION_LOG.md`
- Progress log: `adapter_project/project_control/WORK_LOG.md`

## Important Notes

- Direct game FFB should use `sim_source=vjoy_ffb`; that path does not require SimHub.
- `il` is the practical path for mapping game FFB into current-related Elmo settings.
- This hardware is currently PR-mode capable; true TC torque control is not validated.
- Avoid running old scripts in parallel with GUI-managed runtime.
- If shaft hard-lock occurs, hit `PANIC STOP` first.

## Current Scope

This GUI centralizes control/ownership and conflict prevention for existing scripts.
It does not replace every script internals yet, but it enforces a single master orchestrator.
