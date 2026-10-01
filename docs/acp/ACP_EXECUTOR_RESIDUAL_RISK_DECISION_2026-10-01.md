# ACP Executor Residual-Risk Decision — 2026-10-01

## Decision status

**Profile selected now:** `BOUNDED_LOCAL_TEST`

This decision resolves the current design ambiguity in issues #117 and #118 by retaining explicit residual risk instead of claiming that Windows filesystem/process isolation has been fully solved.

It does **not** authorize live mutation.

## Scope

This decision applies to the current experimental forward/rollback executor work, including review surfaces such as PRs #110, #137, and #139.

Permitted scope remains:

- synthetic or disposable repositories only;
- local engineering tests;
- read-only boundary inspection;
- fail-closed refusal testing;
- no ACP, DGAF, Aetherwake, or other real project repository as a live mutation target.

## Threat model

### In scope for current local-test evidence

- accidental path drift;
- ordinary repository state change between earlier planning and execution;
- symlink/reparse-point traversal attempts detected by current guards;
- multi-hardlink targets rejected by current policy;
- target/parent identity change detectable by existing snapshot/recheck logic;
- malformed or mismatched authorization inputs;
- synthetic race cases already represented by the test surface.

### Not resisted by the current claim

A hostile local peer process with equivalent filesystem/database permissions may race, replace, rename, or otherwise interfere after the final application-level validation and before or during a pathname-based side effect.

The current executor therefore does not claim resistance to a same-privilege malicious local actor.

A different-user/service boundary with enforced ACL separation has not been configured or demonstrated for the executor.

## Issue #117 — filesystem object identity / TOCTOU

### Established bounded evidence

Current hardening work demonstrates:

- canonical path and repository-containment checks;
- `.git` exclusion;
- symlink/reparse-point rejection;
- multi-hardlink policy;
- parent and target object-identity snapshots/rechecks;
- Windows handle-derived identity probing;
- synthetic handle-based delete feasibility;
- synthetic absolute-destination handle rename feasibility;
- adversarial disposable/temp-repository race tests;
- recheck immediately before the current side-effect primitive.

### Residual gap

**Final handle-bound atomic write replacement is NOT ESTABLISHED.**

The strongest current write/replace path still contains a final path-to-syscall interval in which a hostile same-privilege local actor may change filesystem state.

Therefore:

`FINAL_PATH_TO_SYSCALL_TOCTOU=NOT_ELIMINATED`

`HOSTILE_LOCAL_ACTOR_RESISTANCE=NOT_ESTABLISHED`

### Current decision

Do not add disproportionate lower-level Windows object-capability complexity merely to obtain a stronger label.

Retain the residual race explicitly for the current local-test profile.

A future stronger executor profile may reopen this decision and require:

- handle/object-capability-bound final write replacement;
- adversarial proof around the final primitive;
- preserved allowlist/containment/reparse/hardlink/journal/rollback semantics.

## Issue #118 — trusted process / least privilege / OS isolation

### Deployment model selected now

**Disposable local-test executor / interactive engineering tool.**

This is intentionally not a production service, trusted broker, or High-Assurance worker.

### Established bounded evidence

Current work distinguishes:

- application-level `executor_id`;
- SELF_REPORTED_LOCAL process evidence;
- interpreter path/hash/user checks;
- LOCAL_TEST versus HIGH_ASSURANCE assessment;
- read-only Windows ACL/boundary inspection;
- documented stronger service/worker requirements.

### Residual gap

The current local-test process boundary does not establish:

- OS-attested executor identity;
- a trusted launcher or signed/attested binary boundary;
- least-privilege Windows service identity;
- ACL separation among repository roots, authorization store, journal, and rollback custody;
- authenticated IPC preventing peer-process impersonation;
- Job Object/AppContainer/service-SID or equivalent isolation;
- peer-process tamper resistance.

Therefore:

`TRUSTED_PROCESS_IDENTITY=NOT_ESTABLISHED`

`PEER_PROCESS_TAMPER_RESISTANCE=NOT_ESTABLISHED`

`HIGH_ASSURANCE_PROCESS_BOUNDARY=NOT_ESTABLISHED`

### Current decision

Keep the executor in LOCAL_TEST / experimental scope.

A future stronger deployment profile should be a separate tranche built around a dedicated worker/service or broker with:

- explicit executable/launcher identity policy;
- least-privilege Windows identity;
- ACL-separated stores and repository roots;
- authenticated IPC/control path;
- justified OS isolation;
- reproducible disposable-host boundary audit.

## Resulting authorization ceiling

The current ACP executor state remains:

`LIVE_REPOSITORY_MUTATION=NOT_AUTHORIZED`

`ROLLBACK_EXECUTION=NOT_AUTHORIZED`

`PRODUCTION_EXECUTOR=NOT_ESTABLISHED`

`HIGH_ASSURANCE=NOT_AUTHORIZED`

`REAL_PROJECT_MUTATION_TARGETS=NONE`

Passing local synthetic tests, CI, or this residual-risk decision does not change those states.

## Closure meaning

Closing #117 or #118 on the basis of this decision means only:

> The current residual risk and claim ceiling have been explicitly decided for the bounded local-test profile.

It does not mean the underlying stronger security properties were implemented.

If a production or High-Assurance executor is pursued later, the stronger filesystem-object and trusted-process requirements must be reopened under a new deployment-bound gate.
