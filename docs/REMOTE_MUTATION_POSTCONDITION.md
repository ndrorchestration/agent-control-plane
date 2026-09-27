# Remote Mutation Postcondition Verification

Status: **READ-ONLY / NON-EXECUTING POSTCONDITION GATE**.

This tranche observes repository state after an external mutation may have occurred. ACP does not execute the mutation and does not gain execution authority from a successful observation.

## Required upstream evidence

Postcondition verification requires the exact MutationPlan, an admitted pre-execution MutationPathSafetyRecord, and an admitted RollbackCustodyAdmissionRecord whose identities match the same request/resource/operation/plan and rollback descriptor.

## Operation-specific verification

For repo.write_text_file, the target must exist as a regular non-symlink file and its SHA-256 must equal the plan content_sha256.

For repo.delete_file, the target must be absent.

At observation time ACP re-resolves the repository root and target and rejects repository escapes or symlink drift. The repository .git marker must still be present.

## Strong non-effects

The record fixes execution_enabled=false and acp_mutation_executed=false. A verified postcondition means only that the currently observed state matches the exact plan and upstream evidence. It does not prove which actor caused that state transition and does not authorize a future mutation.

## Remaining gates

A separate durable mutation journal/recovery gate now classifies prepared, ambiguous-effect, postcondition-required, verified-postcondition, rollback-ambiguous, verified-rollback, and failure states without enabling execution. Before a live ACP mutation path can be considered, the stack still needs execution receipt/result-evidence binding and a separate explicit mutation-execution authorization gate. TOCTOU between observation and any future action remains unresolved until an execution design composes these controls atomically enough for its threat model.