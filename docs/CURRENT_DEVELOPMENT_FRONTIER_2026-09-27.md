# ACP Current Development Frontier — 2026-09-27

This is the current-facing development overlay for Agent Control Plane (ACP).
Dated audits and evidence documents remain historical records and are not
rewritten to imply later state.

## Accepted mainline

Observed `main` at this checkpoint:

`e5e0eb889f6aea3374c35b2725fb3198616b8139`

Accepted mainline now includes:

- typed read-only remote execution from PR #93;
- bounded task-budget checkpoint/resume from PR #97;
- reconciled non-executing remote-mutation safety stack from PR #112;
- simulation-only mutation composition + adversarial integration coverage from
  PR #121.

Stable typed read-only feature baseline:

`e27a4fa1a5f351eb3a142744be3579eeac4e900c`

## Accepted non-executing mutation safety stack

PR #112 reconciled the strongest previously separate mutation-control contracts
onto current main without adding a live repository mutation executor.

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

The narrow historical PRs remain useful provenance:
#94 → #95 → #96 → #98 → #101 → #103 → #105 → #106 → #108.

PR #104 and PR #107 are closed as superseded after their stronger findings were
ported into the canonical line.

## Accepted simulation-only lane

PR #121 is merged and is the preferred pre-live validation lane.

It composes the accepted control/evidence stack using an in-memory byte mapping
only. It:

- consumes an exact single-use simulation authorization;
- records execution intent before modeled effect;
- applies only typed write/delete semantics in memory;
- records simulated effect evidence;
- derives and verifies a simulation-scoped postcondition;
- binds evidence and closes the authorization;
- preserves fail-closed recovery semantics on interruption.

Durable simulation identities use the `simulation:` namespace to prevent
simulation artifacts from being mistaken for live-execution evidence.

Accepted simulation invariants:

```text
simulation_only=true
live_side_effect_performed=false
acp_mutation_executed=false
```

Reconciled local verification before merge:

- simulation + adversarial focused suite: 16 PASS;
- full ACP regression: 809 PASS / 13 skipped;
- hosted exact-head CI: SUCCESS.

## Experimental live executor — NOT accepted

PR #113 is the bounded repository mutation executor candidate.

It is intentionally **not merged**.

The candidate is disabled by default and limited to typed
`repo.write_text_file` / `repo.delete_file` operations against exact
allowlisted repository roots. Its tests use temporary synthetic repositories
only.

Residual review remains open under:

- #115 — residual High-Assurance executor review;
- #117 — filesystem object identity / handle-bound TOCTOU hardening;
- #118 — trusted process identity, least privilege, and OS isolation;
- #119 — separately authorized rollback executor design.

The current executor threat model explicitly preserves these unresolved
boundaries:

- final filesystem-object TOCTOU is reduced but not eliminated;
- executor binary/process identity is not attested;
- OS sandbox / privilege separation is not established;
- peer-process/store tamper resistance is not established;
- rollback execution is intentionally absent;
- production or DGAF High-Assurance authorization is not established.

## Preferred development order

1. Keep accepted simulation as the default validation lane.
2. Resolve or explicitly bound #117 filesystem-object identity risk.
3. Define the trusted executor/process/ACL boundary in #118.
4. Design rollback as a separately authorized action under #119.
5. Re-run the executor threat model and acceptance criteria in #115.
6. Only then consider a disposable dedicated test-repository exercise.
7. Do not use canonical ACP, DGAF, Aetherwake, or other project repositories as
   the first live target.

## Evidence boundary

Current evidence does **not** establish:

- production-safe live ACP/RDC mutation execution;
- arbitrary command execution;
- authenticated executor/process identity;
- elimination of filesystem TOCTOU;
- independently trusted rollback custody;
- automatic or authorized rollback execution;
- hardware-rooted attestation;
- production security;
- DGAF High-Assurance authorization;
- independent validation;
- scientific efficacy or scientific-N increment.

ACP engineering evidence remains separate from DGAF scientific/evidence-state
promotion and from claims made by consuming research workloads.
