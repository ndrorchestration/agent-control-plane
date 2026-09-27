# ACP Current Development Frontier — 2026-09-27

This is the current-facing development overlay for Agent Control Plane (ACP).
Dated audits and evidence documents remain historical records and are not
rewritten to imply later state.

## Accepted mainline

Observed `main` at this checkpoint:

`6933a09682cf0dcb8b6b9c2aab5ec79330d3c260`

Accepted mainline now includes:

- typed read-only remote execution from PR #93;
- bounded task-budget checkpoint/resume from PR #97;
- reconciled non-executing remote-mutation safety stack from PR #112;
- simulation-only mutation composition + adversarial integration coverage from
  PR #121;
- non-executing repository rollback control/evidence stack from PR #134;
- simulation-only rollback execution composition from PR #135.

Stable typed read-only feature baseline:

`e27a4fa1a5f351eb3a142744be3579eeac4e900c`

## Accepted non-executing mutation safety stack

PR #112 reconciled the strongest mutation-control contracts onto main without
adding a live repository mutation executor.

The accepted stack contains:

- exact mutation authority admission;
- deterministic transaction/precondition/rollback planning;
- exact authority-to-plan composition;
- repository path/symlink/reparse/.git metadata safety;
- rollback-material custody/read-back admission;
- read-only postcondition verification with root/resolved-target continuity;
- durable mutation journal and fail-closed crash/recovery classification;
- execution/result-evidence binding;
- expiring single-use exact-attempt authorization;
- terminal authorization/evidence closure.

Historical narrow lineage:
`#94 → #95 → #96 → #98 → #101 → #103 → #105 → #106 → #108`.

PR #104 and PR #107 are closed as superseded.

## Accepted forward simulation lane

PR #121 is merged and remains the preferred pre-live validation lane for
forward mutation composition.

It uses an in-memory byte mapping only and preserves:

```text
simulation_only=true
live_side_effect_performed=false
acp_mutation_executed=false
```

## Accepted rollback control/evidence stack

PR #134 is merged at
`ae8c98cc2d2f714177af6a0df4a7bded40af6263`.

Accepted rollback controls are non-executing and include:

- explicit rollback plan with distinct rollback request/authority/transaction
  identity;
- dedicated rollback journal;
- read-only repository path/current-state revalidation;
- fail-closed refusal on unsafe concurrent-state drift;
- durable expiring single-use rollback authorization;
- exact original plan / descriptor / custody binding;
- custody-material readback verification before authorization consumption;
- support for recovery planning from eligible post-intent FAILED states.

Legacy authorization-only PR #130 is closed as superseded by this stronger
stack.

Rollback-control evidence does not itself write, delete, rename, or restore a
repository file.

## Accepted rollback simulation lane

PR #135 is merged at
`6933a09682cf0dcb8b6b9c2aab5ec79330d3c260`.

It composes the accepted rollback controls against an in-memory byte mapping
only:

- consumes one exact rollback authorization;
- records rollback intent before modeled effect;
- simulates restore/delete behavior in memory;
- records simulated effect evidence;
- verifies the rollback postcondition;
- closes the rollback journal on verified simulation;
- enters recovery hold when interrupted after intent;
- rejects replay, executor mismatch, current-state drift, wrong rollback
  material, and non-simulation identities.

Accepted rollback-simulation invariants:

```text
simulation_only=true
live_side_effect_performed=false
rollback_executed=false
```

## Experimental forward executor — NOT accepted

PR #113 is the bounded forward repository mutation executor candidate.

It is intentionally **not merged**.

PR #132 is the preferred consolidated hardening-review surface for #113. It
combines:

- #117 filesystem object-identity / TOCTOU hardening;
- #118 executor process-boundary / ACL / isolation assessment;
- #119-adjacent rollback-governance findings relevant to live execution.

Current residual findings remain blocking:

- handle-derived object identity is locally verified;
- handle-based delete and absolute-destination handle rename are verified only
  in synthetic Windows tests;
- parent-directory-handle-relative `FileRenameInfo` is not established on the
  current Windows host and is retained as a strict xfail;
- current executor final side effects remain pathname-based;
- dedicated executor service identity is not established;
- ACL separation among repository, authorization store, journal, and custody is
  not established on the current operator environment;
- OS isolation / peer-process tamper resistance are not established.

Therefore PR #132 remains draft/unmerged.

## Experimental rollback executor — NOT accepted

PR #137 is the bounded repository rollback executor candidate.

It is rebuilt on current main and intentionally remains **draft/unmerged**.

The candidate is:

- disabled unless `experimental_enable=True`;
- limited to exact allowlisted repository roots;
- limited to the two accepted rollback actions:
  - restore prior file bytes;
  - delete a file created by the original mutation;
- required to revalidate current state before authorization consumption;
- required to consume the exact single-use rollback authorization;
- required to record rollback intent before any side effect;
- required to revalidate immediately before the side effect;
- required to report effect evidence and verify postcondition;
- required to enter fail-closed recovery after post-intent failure.

Its side-effect tests are limited to pytest-created disposable repositories.

PR #137 inherits the same unresolved filesystem and process-boundary risks as
the forward executor. No real-project repository rollback is authorized.

## Preferred development order

1. Keep forward and rollback simulation as the default validation lanes.
2. Treat PR #132 as the consolidated live-executor hardening review surface.
3. Resolve or explicitly bound #117 handle-bound filesystem identity limits.
4. Establish an OS-verifiable #118 executor process/ACL/isolation boundary.
5. Keep PR #137 draft until those shared live-executor blockers are resolved.
6. Re-run #115 threat-model acceptance against the hardened forward and
   rollback candidates.
7. Only then consider a disposable dedicated test-repository exercise.
8. Do not use canonical ACP, DGAF, Aetherwake, or another real project
   repository as the first live target.

## Evidence boundary

Current evidence does **not** establish:

- production-safe live ACP/RDC mutation execution;
- production-safe rollback execution;
- real-project repository mutation or rollback authorization;
- arbitrary command execution;
- authenticated executor/process identity;
- elimination of filesystem TOCTOU;
- verified ACL/process isolation;
- peer-process/store tamper resistance;
- hardware-rooted attestation;
- production security;
- DGAF High-Assurance authorization;
- independent validation;
- scientific efficacy or scientific-N increment.

ACP engineering evidence remains separate from DGAF scientific/evidence-state
promotion and from claims made by consuming research workloads.
