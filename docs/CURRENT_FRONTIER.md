# ACP Current Frontier

Date: 2026-10-03

## Purpose

This file is the current public-facing frontier pointer for Agent Control Plane (ACP). Older dated frontier notes remain historical evidence and must not be treated as the current repository state.

## Current protected-main state

Current protected `main` is `7c89db2d54c6ff5b7bd9d1a5cf1af2b4416ecbb2`, through merged PR #152.

Accepted current-main capabilities include:

- typed read-only remote execution;
- action admission;
- remote-mutation admission and exact-plan composition;
- path-safety checks;
- rollback-material custody/readback;
- durable mutation journal/recovery semantics;
- single-use execution authorization and closure;
- read-only postcondition verification;
- execution/result-evidence binding;
- forward-mutation simulation;
- rollback planning, authorization, revalidation, journaling, material readback, and simulation.

Current `main` does **not** contain a live repository mutation executor or rollback executor.

## Current executor profile

Merged PR #149 selected the executor residual-risk profile:

`BOUNDED_LOCAL_TEST`

This permits only bounded engineering work against synthetic or disposable repositories. It does not authorize ACP, DGAF, Aetherwake, or any other real project repository as a mutation target.

Issues #117 and #118 were closed by explicit retained-risk decision, not because stronger filesystem-object or trusted-process guarantees were implemented.

Retained ceilings include:

- `FINAL_PATH_TO_SYSCALL_TOCTOU=NOT_ELIMINATED`
- `HOSTILE_LOCAL_ACTOR_RESISTANCE=NOT_ESTABLISHED`
- `TRUSTED_PROCESS_IDENTITY=NOT_ESTABLISHED`
- `PEER_PROCESS_TAMPER_RESISTANCE=NOT_ESTABLISHED`
- `HIGH_ASSURANCE_PROCESS_BOUNDARY=NOT_ESTABLISHED`
- `LIVE_REPOSITORY_MUTATION=NOT_AUTHORIZED`
- `ROLLBACK_EXECUTION=NOT_AUTHORIZED`
- `PRODUCTION_EXECUTOR=NOT_ESTABLISHED`
- `HIGH_ASSURANCE=NOT_AUTHORIZED`

Issue #154 is the current controller for any fresh current-main reconstruction of a bounded disposable-repository executor.

## Post-execution authority invariant

DGAF protected `main` now makes post-execution authority non-transferable through PR #1257.

ACP must preserve the same invariant in any executor or orchestration composition:

`ACTION -> AUTHORIZATION -> EXECUTION -> RESULT/EVIDENCE -> FRESH ADJUDICATION REQUIRED -> NEW AUTHORIZATION -> FOLLOW-ON ACTION`

An execution result, verified postcondition, receipt, journal closure, or successful result binding is evidence. It is not continuing authority for another consequential action.

A future #154 executor reconstruction must therefore fail closed against chained protected effects unless the follow-on action has independently completed fresh admission/adjudication and obtained a new current authorization.

This cross-system rule does not itself authorize execution.

## Historical queue disposition

Historical executor/recovery PRs are no longer current merge surfaces:

- #109 closed; non-executing result binding was rebuilt and merged through #152.
- #110 closed; historical forward executor candidate superseded by the #149/#154 posture.
- #111 closed; historical journal-recovery branch superseded by current-main semantics.
- #137 closed unmerged; historical rollback executor retained only as evidence.
- #139 closed unmerged; historical consolidated hardening retained only as evidence.

Use issue #154 for any executor reconstruction and current `main` for all interface assumptions.

## Public boundary

ACP remains experimental engineering infrastructure. It is not a production orchestrator, security boundary, autonomous agent runtime, distributed control plane, or independently validated governance system.

Passing simulation, disposable-repository, or hosted CI tests cannot by itself promote real-project mutation, production execution, hostile-local-actor resistance, trusted process identity, High-Assurance, or independent validation.

## Historical frontier notes

`docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md` and `docs/acp/ACP_QUEUE_STATUS_2026-09-30.md` are retained as historical snapshots. Where their queue/blocker language conflicts with this file, this current frontier and the accepted #149/#154 records control.
