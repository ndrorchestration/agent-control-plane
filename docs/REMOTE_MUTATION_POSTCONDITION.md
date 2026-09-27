# Remote Mutation Postcondition Verification

Status: **READ-ONLY / NON-EXECUTING POSTCONDITION GATE**.

This tranche observes repository state after an external mutation may have occurred. ACP does not execute or authorize the mutation and does not gain execution authority from a successful observation.

## Required upstream evidence

Postcondition verification requires the exact MutationPlan, an admitted pre-execution MutationPathSafetyRecord, and an admitted RollbackCustodyAdmissionRecord. The request/resource/operation/plan identity, rollback descriptor SHA-256, and rollback custody reference remain bound into the postcondition record.

The verifier also requires the repository root and resolved target observed at postcondition time to match the previously admitted path-safety root/target identity before accepting current state.

## Operation-specific verification

For repo.write_text_file, the target must exist as a regular non-symlink file and its SHA-256 must equal the plan content_sha256.

For repo.delete_file, the target must be absent.

At observation time ACP re-resolves repository root/target, rejects repository escape or symlink drift, and requires the .git marker to remain present.

## Strong non-effects

Every postcondition record fixes execution_enabled=false and mutation_executed=false. A verified postcondition means only that the currently observed state matches the exact plan and upstream evidence. It does not prove which actor caused the state transition and does not authorize a future mutation.

## Remaining gates

A separate durable mutation journal/recovery gate classifies prepared, ambiguous-effect, postcondition-required, verified-postcondition, rollback-ambiguous, verified-rollback, and failure states without enabling execution. Execution receipt/result-evidence binding and a separate explicit mutation-execution authorization gate remain downstream. TOCTOU between observation and any future action remains unresolved until an execution design composes these controls for its threat model.