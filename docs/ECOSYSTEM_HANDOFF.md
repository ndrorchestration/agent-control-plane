# Ecosystem Handoff: ACP

ACP is an infrastructure track. It should remain decoupled from domain-specific governance, evaluation, acoustic, spatial, mathematical, and scientific-efficacy claims.

## Integration rule

Other repositories may consume ACP through explicit interfaces, but an integration is not considered established until there is a reproducible integration artifact or test. Consuming systems do not inherit ACP engineering evidence as governance, scientific, or production evidence.

## Current accepted boundary

Accepted ACP `main` includes PR #93; the typed read-only feature baseline is `e27a4fa1a5f351eb3a142744be3579eeac4e900c`, establishing the repository's accepted typed read-only remote-execution contract. Signed read-only requests carry typed operation intent and structured parameters; ACP/executor policy derives fixed argv and executes with `shell=False` under bounded local controls.

Cross-runtime portability, production security, authenticated remote transport identity, hardware-rooted attestation, and live remote mutation remain unestablished.

## Active development frontier

Accepted main now also includes merged PR #97 bounded task-budget checkpoint/resume.

The canonical remote-mutation design remains draft/non-executing and is stacked as:

- PR #94 — exact mutation authority admission;
- PR #95 — immutable mutation registry plus transaction/precondition/rollback model;
- PR #96 — exact authority/transaction-plan composition;
- PR #98 — repository mutation path-safety gate;
- PR #101 — rollback-material custody/read-back admission;
- PR #103 — read-only postcondition verification with exact root/resolved-target and rollback/custody identity binding;
- PR #105 — durable mutation journal and fail-closed recovery classification;
- PR #106 — external execution/result-evidence binding;
- PR #108 — exact expiring single-use execution authorization plus terminal closure binding.

All canonical exact heads are GitHub Actions SUCCESS. PR #104 and #107 are closed as superseded after their useful findings were reconciled into #103/#105. No live ACP/RDC mutation executor is established.

See `docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md` for exact heads, verification state, dependency ordering, and remaining gates.

## Boundary examples

- DGAF may supply governance policy logic and adjudication; ACP supplies execution/admission/evidence boundaries. ACP does not self-promote DGAF evidence state.
- Remote Desktop Commander may act as an execution endpoint; it is not an authority source or evidence adjudicator.
- Driftwatch may observe or evaluate ACP behavior; ACP does not inherit Driftwatch's empirical claims.
- Meshsense/ASIS may use orchestration infrastructure; ACP does not validate their spatial/acoustic claims.
- PDMAL/Phi-Calculus research may inform orchestration experiments; ACP does not establish their mathematical or scientific validity.

## Handoff rule for mutation work

Do not wire a live mutation executor merely because #94/#95/#96/#98/#101/#103/#105/#106/#108 pass. The non-executing control/evidence/authorization scaffold now reaches single-use exact-attempt authorization and closure. A live executor still requires a separately reviewed composition that authenticates the executor identity, consumes authorization before side effect, journals intent durably before effect, preserves fixed typed-operation/path/plan identity, verifies postconditions after effect, holds ambiguous interruptions, and separately authorizes rollback/recovery.

## Status

ACP is an active experimental engineering substrate. Accepted mainline and draft-frontier status must remain distinguishable; draft PR evidence does not become merged capability by implication.
