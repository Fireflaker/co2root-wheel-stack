# Next Increment Backlog

## Priority 1 - Manual Integration Evidence

1. Execute `MASTER_GUI_MANUAL_CHECKLIST.md` end-to-end on target hardware.
1. Capture pass/fail evidence per step in `WORK_LOG.md`.
1. Record any failure signatures and immediate remediation guidance.

## Priority 2 - Adapter Input Robustness

1. Collect SimHub websocket payload variants from real sessions.
1. Add tests for malformed/missing force fields and fallback extraction.
1. Update adapter source docs with validated payload handling rules.

## Priority 3 - Steering Calibration and Wraparound

1. Validate long-session center drift behavior under real encoder rollovers.
1. Add a repeatable calibration verification checklist and acceptance bounds.
1. Document corrective action if drift exceeds threshold.

## Priority 4 - Safety Path Hardening

1. Add a dry-run mode for panic/release sequence assertions.
1. Add log signature checks for release-sequence success/failure.
1. Gate release candidate promotion on safety dry-run pass evidence.

## Done Criteria for Next Increment

- Manual checklist executed with evidence and no unresolved critical failures.
- New robustness tests added and passing in staged validation.
- Safety dry-run checks available and documented.
