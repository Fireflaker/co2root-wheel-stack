# Decision Log

## 2026-04-13
- Decision: Enforce single-master GUI ownership via global mutex.
  - Why: Prevent parallel process conflicts and COM contention.
  - Impact: Legacy launch paths must defer to GUI when active.

- Decision: Keep one managed bridge process at a time in GUI.
  - Why: Safety-first and deterministic ownership.
  - Impact: Validation path uses Safe vJoy first, then adapter.

- Decision: Add health check and one-click safe bring-up actions.
  - Why: Reduce operator error and startup variance.
  - Impact: Faster reproducible startup and easier triage.

- Decision: Persist GUI session logs in `adapter_project/logs/master_gui`.
  - Why: Traceability and post-incident debugging.
  - Impact: Better incident analysis and runbook verification.

- Decision: Add baseline unit tests for adapter core math/slew utilities.
  - Why: Catch regressions in command scaling and bounds logic.
  - Impact: Safer iterative tuning.
