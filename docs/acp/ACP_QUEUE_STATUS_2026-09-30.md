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

## Active controller

Issue #154 controls any fresh executor reconstruction.

A #154 implementation must:

1. start from exact current protected `main`;
2. import only the minimum useful disposable-repository side-effect layer;
3. remain explicit opt-in;
4. prohibit ACP, DGAF, Aetherwake, and all other real project repositories as targets;
5. preserve exact allowlists, `.git` exclusion, reparse/symlink/hardlink controls, authorization-consumption ordering, durable intent/journal semantics, postcondition verification, and fail-closed recovery;
6. keep forward-mutation and rollback authorization distinct;
7. preserve the #149 residual-risk ceilings;
8. add adversarial disposable/temp-repository tests;
9. require fresh admission/adjudication and new authorization before any consequential follow-on action.

## Post-execution rule

Successful execution does not carry authority forward.

ACP must interpret execution receipts/results, postconditions, journal closure, and result binding as **evidence only**. Any subsequent consequential action requires fresh adjudication and a new current authorization.

This aligns ACP with DGAF PR #1257 without promoting either system's claim state.

## Smallest safe advancement order

1. Keep #1210/#1256 external-human DGAF evidence collection independent of ACP engineering.
2. Keep ACP simulations as the canonical non-side-effect validation lane.
3. Reconstruct #154 only when a tested execution environment is available.
4. Validate any #154 candidate exclusively against disposable repositories.
5. Do not advance rollback execution until the forward disposable-only contract is clean and independently separated by authorization.
6. Consider stronger production/High-Assurance process and filesystem properties only under a new deployment-bound gate.

## Evidence ceiling

- `ACP_QUEUE_RECONCILED=TRUE`
- `BOUNDED_LOCAL_TEST_PROFILE=SELECTED`
- `BOUNDED_LOCAL_TEST_EXECUTOR=NOT_YET_ESTABLISHED_ON_CURRENT_MAIN`
- `LIVE_REPOSITORY_MUTATION=NOT_AUTHORIZED`
- `ROLLBACK_EXECUTION=NOT_AUTHORIZED`
- `PRODUCTION_EXECUTOR=NOT_ESTABLISHED`
- `HIGH_ASSURANCE=NOT_AUTHORIZED`
