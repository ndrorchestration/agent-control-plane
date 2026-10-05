# ACP Current Frontier

Date: 2026-10-04

## Purpose

This file is the current public-facing frontier pointer for Agent Control Plane (ACP). Older dated frontier notes remain historical evidence and must not be treated as the current repository state.

## Current implementation baseline

The accepted implementation baseline for the current executor/CEP semantics is
`e7135323663ebbe025b18b74a13f2d99c14e2b57`, through merged PR #170. Later
documentation-only commits may advance repository `main` without changing that
implementation baseline. Resolve mutable repository-tip identity from live
GitHub rather than treating this file as a self-referential commit pointer.

The bounded executor posture was established by PR #156 and strengthened by
durable local mutation lineage in PR #159; later CEP/context-efficiency changes
do not widen mutation authority.

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
- bounded disposable-repository mutation execution under the `BOUNDED_LOCAL_TEST` profile;
- typed fresh-adjudication binding for explicitly chained mutation lineage;
- durable local mutation lineage for the tested disposable-repository scope;
- rollback planning, authorization, revalidation, journaling, material readback, and simulation.

Current `main` contains the bounded disposable-repository executor from PR #156. It does **not** contain a rollback executor, and it does not authorize mutation of ACP, DGAF, Aetherwake, or other real project repositories.

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

Issue #154's reconstruction scope is completed by PR #156. The established state is `BOUNDED_LOCAL_TEST_EXECUTOR=ESTABLISHED_FOR_TESTED_DISPOSABLE_SCOPE`; any broader executor profile requires a new deployment-bound controller.

## Post-execution authority invariant

DGAF protected `main` now makes post-execution authority non-transferable through PR #1257.

ACP must preserve the same invariant in any executor or orchestration composition:

`ACTION -> AUTHORIZATION -> EXECUTION -> RESULT/EVIDENCE -> FRESH ADJUDICATION REQUIRED -> NEW AUTHORIZATION -> FOLLOW-ON ACTION`

An execution result, verified postcondition, receipt, journal closure, or successful result binding is evidence. It is not continuing authority for another consequential action.

The merged #156 executor fails closed for explicitly supplied chained lineage unless
the follow-on action carries a typed fresh-adjudication binding to a distinct
current authorization. Merged PR #159 adds durable local mutation lineage so
known prior mutation history cannot be bypassed merely by omitting a supplied
prior closure. That bounded lineage evidence remains scoped to the tested
disposable-repository profile and does not establish distributed/global
lineage, hostile-local-actor resistance, or any broader mutation authority.

This cross-system rule does not itself authorize execution.

## Historical queue disposition

Historical executor/recovery PRs are no longer current merge surfaces:

- #109 closed; non-executing result binding was rebuilt and merged through #152.
- #110 closed; historical forward executor candidate superseded by the #149/#154 posture.
- #111 closed; historical journal-recovery branch superseded by current-main semantics.
- #137 closed unmerged; historical rollback executor retained only as evidence.
- #139 closed unmerged; historical consolidated hardening retained only as evidence.

Treat issue #154 and PR #156 as the completed bounded-reconstruction record, and use current `main` for all interface assumptions. Any stronger executor profile requires a new controller rather than reinterpretation of #154.

## Public boundary

ACP remains experimental engineering infrastructure. It is not a production orchestrator, security boundary, autonomous agent runtime, distributed control plane, or independently validated governance system.

Passing simulation, disposable-repository, or hosted CI tests cannot by itself promote real-project mutation, production execution, hostile-local-actor resistance, trusted process identity, High-Assurance, or independent validation.

## Historical frontier notes

`docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md` and `docs/acp/ACP_QUEUE_STATUS_2026-09-30.md` are retained as historical snapshots. Where their queue/blocker language conflicts with this file, this current frontier and the accepted #149/#154 records control.
