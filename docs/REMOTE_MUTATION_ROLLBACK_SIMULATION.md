# Simulation-Only Repository Rollback Composition

Status: **SIMULATION ONLY / NO FILESYSTEM SIDE EFFECT**.

This gate composes the explicit rollback plan, read-only current-state revalidation, exact single-use rollback authorization, custody-material readback, and rollback journal against an in-memory byte mapping.

Simulation identities must use the `simulation:` namespace. The exact rollback authorization is consumed and `ROLLBACK_INTENT_RECORDED` is journaled, but all effect/postcondition work occurs only in memory.

The simulation proves control-flow and evidence semantics without mutating a repository.

## Strong boundary

- `simulation_only=true`
- `live_side_effect_performed=false`
- `rollback_executed=false`
- no Remote Desktop Commander mutation call
- no filesystem write/delete
- no automatic rollback
- no production/High-Assurance claim

This is the preferred pre-executor validation lane. A future bounded rollback executor remains a separate implementation gate.
