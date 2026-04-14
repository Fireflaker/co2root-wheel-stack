# Research List (Module Completion)

## Objective

Track targeted research items that reduce integration risk and improve long-term maintainability of the game -> telemetry -> wheel control chain.

## Priority A - Immediate (Current Increment)

1. Adapter source robustness

- Investigate websocket payload variants from SimHub for force fields and edge keys.
- Document fallback extraction strategy and malformed payload behavior.

1. Encoder/steering mapping correctness

- Validate count wrap handling assumptions against real encoder rollover behavior.
- Confirm steering center calibration drift behavior over long sessions.

1. Deterministic non-hardware tests

- Identify pure functions in each module and ensure a matching unit test exists.
- Define exclusion list for hardware-coupled code paths requiring manual tests.

## Priority B - Next Increment

1. Safety-path verification automation

- Design a safe dry-run mode for panic and release flow assertions.
- Add log signature checks for release success/failure sequence.

1. Runtime observability

- Evaluate a structured log schema (event id + source + stage + elapsed_ms).
- Add a lightweight parser script for post-session diagnostics summary.

1. Bridge interface contract

- Document expected value ranges and units across adapters:
  - FFB input bounds
  - Torque command bounds
  - Position count normalization

## Priority C - Hardening/Release

1. End-to-end acceptance harness

- Build reproducible checklist/script for launch -> health -> drive -> stop cycle.
- Include known-failure signatures and first-response remediation steps.

1. Performance envelope

- Measure loop jitter under load and identify threshold alerts.
- Define minimum acceptable update rates for telemetry and command loop.

1. Release packaging standards

- Versioned runbook snapshots.
- Branch/release gate checklist with test evidence links.

## Exit Criteria

- Each research item must produce one concrete artifact:
  - test case
  - documented decision
  - runbook update
  - automation script
