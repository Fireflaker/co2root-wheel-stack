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
4. For steering-only validation: click `Start Safe vJoy`.
5. Start SimHub and LFS from GUI buttons.
6. In LFS, map steering to `vJoy X` and verify indicator movement.
7. Only after steering is stable, test `Start Adapter` path.

Alternative:

1. Click `One-Click Safe Bring-up`.
2. Then run `Start Safe vJoy` for steering validation.
3. Then run `Start Adapter` for full loop.

## Health and Logs

- `Health Check` validates:
  - SimHub reachability on `127.0.0.1:8888`
  - Elmo serial openability on configured COM/baud
  - current sim source settings
- Session logs are persisted under `adapter_project/logs/master_gui`.
- Use `Open Logs Folder` to inspect session traces quickly.

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

- This hardware is currently PR-mode based; true TC torque control is not validated.
- Avoid running old scripts in parallel with GUI-managed runtime.
- If shaft hard-lock occurs, hit `PANIC STOP` first.

## Current Scope

This GUI centralizes control/ownership and conflict prevention for existing scripts.
It does not replace every script internals yet, but it enforces a single master orchestrator.
