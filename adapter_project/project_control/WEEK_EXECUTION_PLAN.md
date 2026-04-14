# Week Execution Plan (Master Wheel Control)

## Objective
Deliver a production-ready single-master control flow for game -> telemetry -> control bridge -> Elmo motor with safety gates, diagnostics, and tests.

## Scope Lock
- In scope:
  - Single orchestration GUI runtime ownership
  - SimHub/LFS launch and health checks
  - Safe motor release and panic controls
  - Adapter loop validation and baseline tests
  - Operator docs and runbooks
- Out of scope (this week):
  - Firmware-level Elmo tuning redesign
  - New game plugin development from scratch

## Timeline
- Day 1: Orchestration hardening and process ownership
- Day 2: Telemetry/source reliability checks and startup sequencing
- Day 3: Safety paths and panic/release validation
- Day 4: Debug observability and persistent logs
- Day 5: Automated tests and regression scripts
- Day 6: End-to-end acceptance and issue burn-down
- Day 7: Packaging, final docs, release candidate sign-off

## Daily Deliverables
- Code diffs with compile/lint/test status
- Updated WORK_LOG entries
- Updated DECISION_LOG entries
- Updated runbook examples if behavior changes

## Acceptance Criteria
- One active control owner at a time (GUI-enforced)
- Reliable startup path from one UI
- Panic stop works and release sequence observable in logs
- Tests pass for core adapter math/safety logic
- Operator docs are executable without missing steps
