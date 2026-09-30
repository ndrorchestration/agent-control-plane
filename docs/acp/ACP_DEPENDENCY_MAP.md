# ACP Dependency Map

## Purpose

This map separates ACP work by authority boundary so non-executing documentation, journal semantics, and result-binding work cannot be confused with live repository mutation authority.

## Lanes

ACP work is divided into three advancement lanes.

### 1. Non-executing rollback-recovery journal semantics

Representative PR:

- #111

Status:

- Candidate for future advancement only after clean rebuild from `main`.
- Does not authorize rollback execution.
- Does not introduce a rollback executor.
- Should remain separate from executor authority.

Dependencies:

- Current protected `main`
- Journal state-transition semantics
- Existing non-mutating evidence conventions
- Verification that recovery semantics do not imply live rollback execution

### 2. Non-executing result binding

Representative PR:

- #109

Status:

- Candidate for future advancement only after clean rebuild from `main`.
- Binds results to evidence/state without executing repository mutation.
- Must not be represented as executor authorization.

Dependencies:

- Current protected `main`
- Result-binding evidence contract
- Non-mutating run identity conventions
- Explicit statement that `execution_authorized=false` and `acp_mutation_executed=false` remain true

### 3. Executor / mutation authority

Representative PRs:

- #110
- #137
- #139

Status:

- HOLD.
- Review-only until boundary model is explicit.
- Not currently a merge lane.

Dependencies:

- #117 — filesystem object identity / TOCTOU boundary
- #118 — trusted process boundary / identity / isolation
- Mutation evidence contract
- Rollback evidence contract
- Fail-closed executor policy

## Dependency diagram

```text
ACP rollback-recovery journal semantics
  -> rebuild from main
  -> may advance only as non-mutating journal semantics
  -> must not imply rollback executor authorization

ACP non-executing result binding
  -> rebuild from main
  -> may advance only as non-mutating evidence binding
  -> must preserve execution_authorized=false

ACP live executor
  -> blocked by #117
  -> blocked by #118
  -> requires mutation evidence contract
  -> requires fail-closed executor policy
  -> remains HOLD

ACP rollback executor
  -> blocked by #117
  -> blocked by #118
  -> requires rollback evidence contract
  -> remains HOLD

ACP executor hardening
  -> review surface only
  -> remains HOLD until boundary model exists
```

## Non-negotiable boundary

No ACP component may cross from observation, journal semantics, or result-binding into live repository mutation unless the trusted executor boundary and filesystem object-identity rules are explicit, reviewed, and fail-closed.

## Current dependency status

| Dependency | Type | Current state |
|---|---|---|
| #117 object identity model | Architecture dependency | Missing / blocker |
| #118 trusted process model | Architecture dependency | Missing / blocker |
| Mutation evidence contract | Governance dependency | Needs definition before promotion |
| Rollback evidence contract | Governance dependency | Needs definition before promotion |
| PR classification metadata | Documentation dependency | Queue-level update required |
| ACP dependency map | Documentation dependency | This document |
| CI guard for HOLD PRs | Workflow dependency | Optional later step |
