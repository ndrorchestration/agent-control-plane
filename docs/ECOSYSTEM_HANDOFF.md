# Ecosystem Handoff: ACP

ACP is an infrastructure track. It should remain decoupled from domain-specific governance, evaluation, acoustic, spatial, mathematical, and scientific-efficacy claims.

## Integration rule

Other repositories may consume ACP through explicit interfaces, but an integration is not considered established until there is a reproducible integration artifact or test. Consuming systems do not inherit ACP engineering evidence as governance, scientific, or production evidence.

## Current accepted boundary

Accepted ACP `main` includes PR #93 at `e27a4fa1a5f351eb3a142744be3579eeac4e900c`, establishing the repository's current typed read-only remote-execution contract. Signed read-only requests carry typed operation intent and structured parameters; ACP/executor policy derives fixed argv and executes with `shell=False` under bounded local controls.

Cross-runtime portability, production security, authenticated remote transport identity, hardware-rooted attestation, and live remote mutation remain unestablished.

## Active development frontier

Mutation-capable design is being decomposed into stacked, non-executing draft layers:

- PR #94 — exact mutation authority admission (`execution_enabled=false`);
- PR #95 — immutable mutation registry plus precondition/rollback transaction model (`mutation_executed=false`);
- PR #96 — exact authority/transaction-plan composition to prevent plan substitution (`mutation_executed=false`).

See `docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md` for exact heads, verification state, dependency ordering, and remaining gates.

## Boundary examples

- DGAF may supply governance policy logic and adjudication; ACP supplies execution/admission/evidence boundaries. ACP does not self-promote DGAF evidence state.
- Remote Desktop Commander may act as an execution endpoint; it is not an authority source or evidence adjudicator.
- Driftwatch may observe or evaluate ACP behavior; ACP does not inherit Driftwatch's empirical claims.
- Meshsense/ASIS may use orchestration infrastructure; ACP does not validate their spatial/acoustic claims.
- PDMAL/Phi-Calculus research may inform orchestration experiments; ACP does not establish their mathematical or scientific validity.

## Handoff rule for mutation work

Do not wire a live mutation executor merely because #94/#95/#96 pass. Operation-specific path/reparse-point/repository-metadata defenses, rollback-material custody, postcondition verification, crash/interruption recovery, execution evidence, and a separate explicit mutation-execution authorization gate remain prerequisites.

## Status

ACP is an active experimental engineering substrate. Accepted mainline and draft-frontier status must remain distinguishable; draft PR evidence does not become merged capability by implication.
