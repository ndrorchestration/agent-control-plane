# ACP Current Development Frontier — 2026-09-27

This is the current-facing development overlay for Agent Control Plane (ACP).
Dated audits and evidence documents remain historical records and are not
rewritten to imply later state.

## Accepted mainline

Observed `main` at this checkpoint:

`954706a98adae7edd40132c7f49370c11f5f0186`

Accepted mainline includes:

- typed read-only remote execution from PR #93;
- bounded task-budget checkpoint/resume from PR #97;
- reconciled non-executing remote-mutation safety stack from PR #112;
- simulation-only mutation composition + adversarial integration coverage from
  PR #121;
- non-executing repository rollback control/evidence stack from PR #134;
- simulation-only rollback execution composition from PR #135;
- rollback-control / executor-frontier documentation reconciliation from PR #138.

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

PR #139 at exact head
`dde9140cc158b536e77a9930e2c1f3ec98abcb93` is the latest consolidated
forward-executor hardening review surface and has GitHub Actions SUCCESS.

It reconciles the previously separate implementation surfaces:

- #123 primitive-entry junction/reparse/multi-hardlink guard;
- #124 SELF_REPORTED_LOCAL process-identity preflight and Windows deployment
  boundary;
- #126 object-identity drift checks plus Windows handle-feasibility probes;
- #128 LOCAL_TEST/HIGH_ASSURANCE process-boundary assessment and reproducible
  read-only Windows ACL/process audit;
- #132's earlier combined object-identity/process-boundary integration.

PRs #123, #124, #126, #128, and #132 are closed as superseded by #139.

**Important reconciliation update:** #139 is no longer a complete representation
of the newest #117/#118 experimental evidence. Both dedicated hardening branches
advanced after #139 from the same executor base and now diverge from #139:

- #117 latest recorded branch head
  `6d3d8076a48b10b43561791d1d930aa0e3f86d1b` is 7 commits ahead / 18 behind
  #139. Synthetic local Windows evidence verifies NT-native handle-relative
  rename with a held parent-directory handle, and an experimental Windows-only
  handle-mutation adapter exists. That adapter is not wired into the executor
  effect path.
- #118 latest recorded branch head
  `b276dd55ffbd77d07481c6bad042859e6b59bfd4` is 31 commits ahead / 18 behind
  #139. Disposable-lab service process identity is verified, a restricted
  service SID is operational, and a reversible minimal-service-token trial
  verified an exact `SeChangeNotifyPrivilege` token policy.

Those advances do **not** establish the production boundary. Current residual
findings remain blocking:

- handle-bound atomic write replacement in the ACP executor is not implemented;
- final TOCTOU elimination is not established;
- the NT-native rename path is platform-specific experimental evidence and lacks
  cross-Windows-version/filesystem validation;
- the verified service identity applies to a disposable inert lab probe, not an
  accepted production executor;
- the minimal service-token policy was verified experimentally and then rolled
  back; it is not currently enforced;
- trusted-launcher identity is not established;
- ACL separation among repository, authorization store, journal, and custody is
  not established as an accepted production boundary;
- complete OS isolation / peer-process tamper resistance are not established.

Therefore PR #139 remains draft/unmerged, and a **fresh reconciliation surface**
is required before it can again be described as the complete current hardening
surface.

## Experimental rollback executor — NOT accepted

PR #137 at exact head
`bc603c5002d21eb267821b012b01e95cd9bc2efe` is the bounded repository
rollback executor candidate. Its hosted test surface is green.

It is rebuilt on accepted rollback controls and intentionally remains
**draft/unmerged**.

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

PR #137 inherits the unresolved filesystem and process-boundary risks above.
No real-project repository rollback is authorized.

## Preferred development order

1. Keep forward and rollback simulation as the default validation lanes.
2. Reconcile the post-#139 #117 and #118 branches into one fresh integration
   candidate without weakening either branch's evidence ceiling.
3. Exercise the verified Windows handle-relative adapter only in disposable
   repository fixtures through the existing authorization/intent/postcondition
   lifecycle.
4. Convert the verified disposable-service identity/minimal-token evidence into
   an accepted executor boundary only after trusted-launcher, ACL, isolation,
   and tamper-resistance controls are separately established.
5. Keep PR #137 draft until the shared live-executor blockers are resolved.
6. Re-run #115 threat-model acceptance against the freshly reconciled forward
   and rollback candidates.
7. Only then consider a disposable dedicated test-repository exercise.
8. Do not use canonical ACP, DGAF, Aetherwake, or another real project
   repository as the first live target.

## Evidence boundary

Current evidence does **not** establish:

- production-safe live ACP/RDC mutation execution;
- production-safe rollback execution;
- real-project repository mutation or rollback authorization;
- arbitrary command execution;
- trusted production executor/launcher identity;
- handle-bound atomic write replacement in the accepted executor;
- final elimination of filesystem TOCTOU;
- accepted production ACL/process isolation;
- peer-process/store tamper resistance;
- hardware-rooted attestation;
- production security;
- DGAF High-Assurance authorization;
- independent validation;
- scientific efficacy or scientific-N increment.

ACP engineering evidence remains separate from DGAF scientific/evidence-state
promotion and from claims made by consuming research workloads.
