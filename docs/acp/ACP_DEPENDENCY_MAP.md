# ACP Dependency Map

## Purpose

This map separates ACP work by authority boundary so observation, evidence, simulation, disposable-only execution, and real-project execution cannot be conflated.

## Current lanes

### 1. Observation and read-only execution

Status: accepted bounded engineering capability on `main`.

This lane may emit evidence but does not grant mutation authority.

### 2. Non-executing mutation governance

Accepted current-main primitives include:

- admission;
- transaction/precondition modeling;
- exact composition;
- path safety;
- rollback custody/readback;
- durable journal/recovery;
- postcondition verification;
- result binding;
- execution authorization/closure;
- forward simulation;
- rollback plan/authorization/revalidation/journal/simulation.

Status: present on protected `main`.

These controls define and test mutation semantics but do not themselves perform repository mutation.

### 3. Bounded disposable-repository executor

Controller: issue #154.

Status: not yet established on current `main`.

Dependencies:

- exact current-main interfaces;
- accepted #149 `BOUNDED_LOCAL_TEST` residual-risk profile;
- explicit opt-in;
- disposable/synthetic repository target proof;
- exact-root allowlist and Git-metadata exclusion;
- path/reparse/symlink/hardlink checks;
- authorization consumption before side effect;
- durable execution intent before side effect;
- postcondition verification;
- result/evidence binding;
- fail-closed recovery;
- no authority transfer to follow-on actions.

A successful #154 rebuild may establish only:

`BOUNDED_LOCAL_TEST_EXECUTOR=ESTABLISHED_FOR_TESTED_DISPOSABLE_SCOPE`

### 4. Rollback executor

Status: not authorized.

Rollback is a distinct privileged mutation action. Forward-execution authorization does not transfer to rollback.

A rollback executor requires its own current authorization, custody/plan/revalidation binding, intent journal, postcondition, evidence, and claim ceiling.

### 5. Real-project / production / High-Assurance execution

Status: not authorized / not established.

A stronger future lane must reopen deployment-bound requirements including:

- final object-capability/TOCTOU treatment;
- trusted executable/process identity;
- least-privilege service identity;
- ACL-separated stores and repository roots;
- authenticated control/IPC path;
- justified OS isolation;
- peer-process tamper resistance;
- deployment-specific evidence and independent review.

## Dependency diagram

```text
read-only observation/execution
  -> evidence

non-executing mutation governance on main
  -> admission
  -> exact plan
  -> path / rollback custody
  -> journal / authorization
  -> simulation
  -> postcondition / result binding
  -> closure

#154 bounded local-test executor
  -> exact current main
  -> #149 BOUNDED_LOCAL_TEST profile
  -> disposable-repository proof
  -> side effect
  -> result/postcondition evidence
  -> authority effect = NONE
  -> fresh adjudication required for any follow-on effect

rollback executor
  -> separate rollback authorization
  -> remains NOT AUTHORIZED

real-project / production / High-Assurance executor
  -> new deployment-bound gate
  -> stronger filesystem/process guarantees
  -> independent review
  -> remains NOT ESTABLISHED
```

## Cross-system authority invariant

DGAF PR #1257 establishes that execution evidence does not transfer authority.

ACP must preserve this property:

- prior success is evidence, not permission;
- a closed transaction is not reusable authorization;
- a verified postcondition does not authorize the next mutation;
- retries after uncertain outcomes remain reconciliation-controlled;
- rollback is separately authorized;
- chained protected effects require fresh admission/adjudication and new authorization.

## Current dependency status

| Dependency | Type | Current state |
|---|---|---|
| Current protected main | Source identity | `7c89db2d54c6ff5b7bd9d1a5cf1af2b4416ecbb2` |
| #149 residual-risk decision | Profile dependency | Accepted: `BOUNDED_LOCAL_TEST` |
| #154 executor reconstruction | Implementation dependency | Open / not yet established |
| Forward simulation | Engineering evidence | Present |
| Rollback simulation | Engineering evidence | Present |
| Post-execution fresh-adjudication invariant | Governance dependency | Required for any future executor composition |
| Real-project mutation authority | Authorization dependency | NOT AUTHORIZED |
| Production executor | Assurance dependency | NOT ESTABLISHED |
| High-Assurance executor | Assurance dependency | NOT AUTHORIZED |
