# Ecosystem Handoff: ACP

ACP is an infrastructure track. It should remain decoupled from domain-specific governance, evaluation, acoustic, spatial, mathematical, and scientific-efficacy claims.

## Integration rule

Other repositories may consume ACP through explicit interfaces, but an integration is not considered established until there is a reproducible integration artifact or test. Consuming systems do not inherit ACP engineering evidence as governance, scientific, or production evidence.

## Current accepted boundary

Accepted ACP `main` includes PR #93; the typed read-only feature baseline is `e27a4fa1a5f351eb3a142744be3579eeac4e900c`, establishing the repository's accepted typed read-only remote-execution contract. Signed read-only requests carry typed operation intent and structured parameters; ACP/executor policy derives fixed argv and executes with `shell=False` under bounded local controls.

Cross-runtime portability, production security, authenticated remote transport identity, hardware-rooted attestation, and live remote mutation remain unestablished.

## Active development frontier

Use `docs/CURRENT_FRONTIER.md` as the current public-facing frontier pointer. Dated frontier files, including `docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md`, are retained as historical evidence for the exact source state they describe.

The historical 2026-09-27 frontier recorded that accepted main included PR #97 bounded task-budget checkpoint/resume and that the canonical remote-mutation design remained draft/non-executing across the #94/#95/#96/#98/#101/#103/#105/#106/#108 stack. That historical state should not be read as a current complete inventory without checking `docs/CURRENT_FRONTIER.md` and current `main`.

No live ACP/RDC mutation executor is established by this handoff document.

## Boundary examples

- DGAF may supply governance policy logic and adjudication; ACP supplies execution/admission/evidence boundaries. ACP does not self-promote DGAF evidence state.
- Remote Desktop Commander may act as an execution endpoint; it is not an authority source or evidence adjudicator.
- Driftwatch may observe or evaluate ACP behavior; ACP does not inherit Driftwatch's empirical claims.
- Meshsense/ASIS may use orchestration infrastructure; ACP does not validate their spatial/acoustic claims.
- PDMAL/Phi-Calculus research may inform orchestration experiments; ACP does not establish their mathematical or scientific validity.

## Handoff rule for mutation work

Do not wire a live mutation executor merely because historical non-executing control/evidence/authorization scaffolds passed. A live executor still requires a separately reviewed composition that authenticates the executor identity, consumes authorization before side effect, journals intent durably before effect, preserves fixed typed-operation/path/plan identity, verifies postconditions after effect, holds ambiguous interruptions, and separately authorizes rollback/recovery.

## Status

ACP is an active experimental engineering substrate. Accepted mainline and draft-frontier status must remain distinguishable; draft PR evidence does not become merged capability by implication.
