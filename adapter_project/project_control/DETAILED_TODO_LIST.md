# Detailed TODO List (Incremental Completion)

## Goal

Incrementally close module reliability and test coverage gaps while preserving safe bring-up and operational repeatability.

## Execution Order

### Phase 1 - Planning and Baseline

- [x] Confirm current baseline tests pass (`python -m unittest discover -s tests -p "test_*.py"`).
- [x] Freeze acceptance criteria for this increment:
  - [x] All pure utility functions in core modules have deterministic tests.
  - [x] Incremental staged validation command exists and runs locally.
  - [x] Work log is appended after each completed stage.

### Phase 2 - Module Test Process Buildout

- [x] Adapter core (`adapter_main.py`)
  - [x] Add tests for config loading behavior (default create + merge override).
  - [x] Add tests for source factory dispatch (`serial/http/websocket/inject`).
  - [x] Add tests for extractor helpers in HTTP/WebSocket source classes.
- [x] Wheel bridge (`wheel_sim_bridge.py`)
  - [x] Add tests for integer parsing and PX extraction.
  - [x] Add tests for 16-bit conversion and steering normalization boundaries.
  - [x] Add tests for centered steering wraparound correctness.
- [ ] Master GUI (`master_control_gui.py`)
  - [x] Keep current runtime checks (health/bring-up) as integration/manual path.
  - [x] Capture manual verification checklist and expected outcomes.

### Phase 3 - Incremental Validation Automation

- [x] Add staged validation script with named stages:
  - [x] `compile`
  - [x] `unit`
  - [x] `full`
- [x] Ensure script supports optional stage selection and fail-fast output.
- [x] Ensure script appends successful run note to `WORK_LOG.md`.

### Phase 4 - Incremental Execution

- [x] Run compile stage and confirm pass.
- [x] Run unit stage and confirm pass.
- [x] Run full stage and confirm pass.
- [x] Record findings and any follow-up work.

### Phase 5 - Completion Gate

- [ ] Verify no diagnostics errors in touched files.
- [x] Verify no diagnostics errors in touched files.
- [x] Confirm docs reference staged validation command.
- [ ] Publish completion summary and next increment backlog.
- [x] Publish completion summary and next increment backlog.

## Definition of Done

- [x] Added detailed TODO and research list.
- [x] Added module-level test process and expanded tests.
- [x] Executed incremental tests with passing results.
- [x] Updated work log with timestamped validation entries.

## Completion Artifacts

- Manual integration checklist: `project_control/MASTER_GUI_MANUAL_CHECKLIST.md`
- Increment completion summary: `project_control/INCREMENT_COMPLETION_SUMMARY.md`
- Next increment backlog: `project_control/NEXT_INCREMENT_BACKLOG.md`
