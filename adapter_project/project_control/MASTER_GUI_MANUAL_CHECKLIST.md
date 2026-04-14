# Master GUI Manual Integration Checklist

## Scope

Manual verification path for `master_control_gui.py` orchestration and safety behavior.
Use this after code changes that affect process control, serial safety, or bring-up sequencing.

## Preconditions

- Hardware connection is physically safe and operator is present.
- SimHub is installed and expected local endpoint is configured.
- Elmo drive COM/baud in config matches target hardware.
- No legacy bridge or adapter scripts are running.

## Checklist

1. Launch master GUI

- Action: Run `start_master_gui.ps1`.
- Expected: Single GUI instance opens; no duplicate instance appears.
- Evidence: Session log file created under `logs/master_gui`.

1. Conflict cleanup

- Action: Click `Kill Conflicts`.
- Expected: Any old bridge/adapter worker processes are terminated.
- Evidence: Log lines indicate conflict scan and cleanup completion.

1. Drive probe

- Action: Click `Probe Drive`.
- Expected: Probe reports readable responses for `MO`, `EC`, `UM`, and `PX`.
- Evidence: Probe response block present in GUI output/log.

1. Health check

- Action: Click `Health Check`.
- Expected:
  - SimHub endpoint check returns reachable.
  - Elmo serial openability check returns OK.
  - Active sim source mode is printed.
- Evidence: Health summary in GUI output/log.

1. Safe steering path

- Action: Click `Start Safe vJoy`.
- Expected: Bridge starts in steering-safe mode and indicator updates when sim steering changes.
- Evidence: Process start log + visible vJoy axis movement.

1. One-click safe bring-up

- Action: Click `One-Click Safe Bring-up`.
- Expected: Ordered sequence executes without error, no duplicate managed process.
- Evidence: Ordered stage log entries with success markers.

1. Full adapter path

- Action: Click `Start Adapter` only after safe steering is stable.
- Expected: Adapter process starts under GUI ownership and remains stable.
- Evidence: Managed process PID log and no repeated restart churn.

1. Panic stop safety

- Action: Click `PANIC STOP` while managed process is active.
- Expected:
  - Managed process stops.
  - Conflict killer executes.
  - Release sequence (`ST`, `TC=0`, `MO=0`) is issued.
- Evidence: Log contains stop path and release sequence confirmation.

1. Controlled close behavior

- Action: Close GUI window.
- Expected: Shutdown path respects `motor_off_on_exit` and no orphan worker remains.
- Evidence: Exit log section and post-close process list is clean.

## Pass Criteria

- All checklist items complete with expected outcomes.
- No unexpected exceptions in session logs.
- No orphan adapter/bridge worker after close.

## Failure Handling

- If shaft hard-lock or unsafe behavior occurs, use `PANIC STOP` first.
- Capture log file and exact step number where failure occurred.
- Add an entry to `WORK_LOG.md` with failure signature and recovery action.
