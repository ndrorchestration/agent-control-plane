# ACP Queue Status — Reconciled 2026-10-03

## State

The historical 2026-09-30 PR queue has been resolved. No historical executor branch should be treated as a current merge surface.

This record does not authorize live repository mutation, rollback execution, production deployment, DGAF High-Assurance status, or independent validation.

## Historical PR disposition

| PR | Historical classification | Current disposition |
|---|---|---|
| #109 | Non-executing result-binding tranche | Closed. Superseded by current-main rebuild #152, merged as `7c89db2d54c6ff5b7bd9d1a5cf1af2b4416ecbb2`. |
| #110 | Forward repository mutation executor candidate | Closed. Historical evidence only; do not merge/reopen as the current executor surface. |
| #111 | Rollback-recovery journal semantics | Closed. Historical branch superseded by current-main journal/recovery semantics. |
| #137 | Rollback executor candidate | Closed unmerged. Historical evidence only. |
| #139 | Consolidated executor-hardening surface | Closed unmerged. Historical evidence only. |

## Residual-risk disposition

Issues #117 and #118 are closed by the explicit residual-risk decision merged through PR #149.

This means the current profile intentionally retains, rather than solves:

- final path-to-syscall TOCTOU;
- hostile same-privilege local actor risk;
- lack of OS-attested executor identity;
- lack of peer-process tamper resistance;
- lack of a High-Assurance process boundary.

The selected profile is `BOUNDED_LOCAL_TEST`.

## Completed bounded reconstruction

Issue #154 is completed by merged PR #156 at protected-main commit `b975aeb178b07551869ea6e80421e473ecb48593`.

The accepted bounded implementation:

1. starts from the reconciled current-main interfaces;
2. imports only the minimum disposable-repository side-effect layer;
3. remains explicit opt-in and exact-root allowlisted;
4. requires an explicit disposable-test repository marker and leaves real-project mutation unauthorized;
5. preserves path-safety revalidation, authorization-consumption ordering, durable intent/journal semantics, postcondition verification, evidence binding, closure, and fail-closed recovery;
6. keeps forward-mutation and rollback authorization distinct;
7. preserves the #149 residual-risk ceilings;
8. is covered by hosted disposable/temp-repository tests;
9. emits non-transferable authority semantics and requires typed fresh-adjudication binding for explicitly supplied chained lineage.

## Post-execution rule

Successful execution does not carry authority forward.

ACP must interpret execution receipts/results, postconditions, journal closure, and result binding as **evidence only**. Any subsequent consequential action requires fresh adjudication and a new current authorization.

This aligns ACP with DGAF PR #1257 without promoting either system's claim state.

## Smallest safe advancement order

1. Keep #1210/#1256 external-human DGAF evidence collection independent of ACP engineering.
2. Keep ACP simulations as the canonical non-side-effect validation lane.
3. Keep the merged #156 executor restricted to disposable repositories and treat `BOUNDED_LOCAL_TEST_EXECUTOR=ESTABLISHED_FOR_TESTED_DISPOSABLE_SCOPE` as the ceiling.
4. Do not advance rollback execution until a separate rollback-executor gate is explicitly opened and independently authorized.
5. Open a new deployment-bound controller before considering real-project, production, or High-Assurance execution.
6. Preserve durable cross-invocation resource/effect lineage as a future stronger-profile requirement rather than implying it exists in #156.

## Evidence ceiling

- `ACP_QUEUE_RECONCILED=TRUE`
- `BOUNDED_LOCAL_TEST_PROFILE=SELECTED`
- `BOUNDED_LOCAL_TEST_EXECUTOR=ESTABLISHED_FOR_TESTED_DISPOSABLE_SCOPE`
- `LIVE_REPOSITORY_MUTATION=NOT_AUTHORIZED`
- `ROLLBACK_EXECUTION=NOT_AUTHORIZED`
- `PRODUCTION_EXECUTOR=NOT_ESTABLISHED`
- `HIGH_ASSURANCE=NOT_AUTHORIZED`
