# ACP Executor Boundary Model

## Purpose

This document defines ACP's current executor boundary after the `BOUNDED_LOCAL_TEST` residual-risk decision.

ACP distinguishes:

1. read-only observation/execution;
2. non-executing admission, journal, evidence, and simulation;
3. bounded disposable-repository execution;
4. real-project mutation;
5. rollback execution;
6. production / High-Assurance execution.

These categories are not interchangeable.

## 1. Current profile

Merged PR #149 selected:

`BOUNDED_LOCAL_TEST`

Issues #117 and #118 are therefore closed by retained-risk decision, not by implementation of their strongest proposed controls.

The current profile permits engineering evaluation against synthetic/disposable repositories only.

It does not authorize ACP, DGAF, Aetherwake, or any other real project repository as a mutation target.

## 2. Filesystem object identity / TOCTOU

### Established bounded controls

Current evidence includes:

- canonical path and repository-containment checks;
- `.git` exclusion;
- symlink/reparse-point rejection;
- multi-hardlink rejection policy;
- parent/target identity snapshots and rechecks in historical hardening evidence;
- Windows handle-derived identity probes;
- repeated revalidation before side-effect primitives;
- adversarial disposable/temp-repository race tests in historical evidence.

### Retained gap

Final handle-bound atomic write replacement is not established.

Therefore:

- `FINAL_PATH_TO_SYSCALL_TOCTOU=NOT_ELIMINATED`
- `HOSTILE_LOCAL_ACTOR_RESISTANCE=NOT_ESTABLISHED`

A future production or High-Assurance profile must reopen this boundary.

## 3. Trusted process boundary / identity / isolation

### Established bounded controls

Current evidence distinguishes:

- application-level executor identifiers;
- self-reported local process identity evidence;
- interpreter path/hash/user checks in historical hardening evidence;
- local-test versus High-Assurance assessment;
- read-only Windows boundary/ACL inspection.

### Retained gap

The current profile does not establish:

- OS-attested executor identity;
- trusted launcher/binary identity;
- least-privilege service identity;
- ACL-separated authorization/journal/custody/repository stores;
- authenticated IPC;
- OS sandbox/isolation;
- peer-process tamper resistance.

Therefore:

- `TRUSTED_PROCESS_IDENTITY=NOT_ESTABLISHED`
- `PEER_PROCESS_TAMPER_RESISTANCE=NOT_ESTABLISHED`
- `HIGH_ASSURANCE_PROCESS_BOUNDARY=NOT_ESTABLISHED`

## 4. Mutation evidence contract

Any disposable-only executor candidate must retain evidence for:

- requested action;
- exact plan/action digest;
- authorized target;
- pre-mutation path/object evidence;
- executor identifier and declared profile;
- authorization identity and consumption;
- durable execution intent;
- mutation result;
- postcondition evidence;
- journal/recovery state;
- result/evidence binding;
- closure;
- explicit non-transfer of authority.

## 5. Post-execution authority boundary

Execution success does not create continuing authority.

For every consequential follow-on action, ACP must require a fresh admission/adjudication path and a new current authorization.

The required conceptual sequence is:

`ACTION -> AUTHORIZATION -> EXECUTION -> EVIDENCE -> FRESH ADJUDICATION -> NEW AUTHORIZATION -> NEXT ACTION`

A result receipt, successful postcondition, evidence binding, or transaction closure may be an input to the next adjudication. It cannot itself satisfy that adjudication or authorize the next action.

This aligns ACP with DGAF PR #1257.

## 6. Rollback boundary

Rollback is also mutation and is separately authorized.

A forward mutation authorization cannot be reused as rollback authorization.

Rollback evidence must include:

- original mutation reference;
- rollback plan/custody identity;
- rollback authorization identity;
- pre-rollback state;
- durable rollback intent;
- rollback effect;
- post-rollback verification;
- residual state and recovery outcome.

## 7. Current authorization state

As of 2026-10-03:

- Non-executing mutation governance stack: present on protected `main`.
- Forward mutation simulation: present.
- Rollback simulation: present.
- Bounded local-test executor on current main: not yet established; issue #154 controls reconstruction.
- Live real-project repository mutation: NOT AUTHORIZED.
- Rollback execution: NOT AUTHORIZED.
- Production executor: NOT ESTABLISHED.
- High-Assurance executor: NOT AUTHORIZED.

## 8. Promotion rule

A #154 candidate may advance only as a disposable-repository local-test executor and only after exact-head tests demonstrate the accepted safeguards and ceilings.

Passing those tests cannot establish:

- real-project mutation authority;
- production readiness;
- hostile-local-actor resistance;
- trusted process identity;
- independent validation;
- High-Assurance.

Any stronger profile requires a new deployment-bound gate rather than reinterpretation of `BOUNDED_LOCAL_TEST`.
