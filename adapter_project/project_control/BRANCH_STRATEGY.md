# Branch Strategy

## Recommended Branches
- `main`: stable operator-ready baseline
- `feat/master-gui-orchestration`: orchestration and UX controls
- `feat/safety-and-health`: panic/release/health checks and safeguards
- `feat/tests-and-validation`: test harness and acceptance scripts
- `release/master-gui-v1`: release candidate branch for final QA

## Merge Policy
- Rebase feature branches before merge
- No direct commits to `main` during hardening
- Merge only when:
  - compile checks pass
  - test suite passes
  - runbook updated for behavior changes

## Commit Convention
- `feat(gui): ...`
- `feat(safety): ...`
- `test(adapter): ...`
- `docs(runbook): ...`
- `chore(cleanup): ...`
