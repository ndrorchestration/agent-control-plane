# Remote Mutation Execution Authorization and Closure

Status: **AUTHORIZATION CONTRACT ONLY / NO ACP MUTATION EXECUTOR**.

This tranche defines the final explicit authorization boundary for one external repository mutation attempt. It does not contain or invoke a mutation executor.

## Issuance requirements

An authorization can be issued only when all exact pre-execution records agree on the same request, authority, resource, operation, plan SHA-256, rollback descriptor, and custody reference:

- admitted mutation composition;
- transaction preconditions verified and rollback identity available;
- admitted path-safety record;
- admitted rollback-custody record with verified readback;
- durable mutation journal still exactly in PREPARED state.

Authorization is bound to one named executor ID and one journal transaction ID. The authorization has canonical identity, an issue time, expiry time, and a durable consumed_at field.

## Consumption semantics

Consumption is an atomic SQLite update. The caller must provide the exact authorization ID, executor ID, transaction ID, and plan SHA-256. Consumption fails closed when the token is unknown, already consumed, not yet active, expired, or identity-mismatched.

A consumed authorization permits only the named external executor to attempt the exact bound mutation. It does not authorize a different plan, path, transaction, executor, or later retry.

## Closure semantics

Post-execution closure requires:

- the exact authorization was consumed;
- authorization consumption occurred no later than the journal execution-intent event;
- executor/transaction/request/resource/operation/plan identity matches the bound execution-evidence receipt;
- the evidence receipt is bound;
- the journal is terminal at POSTCONDITION_VERIFIED.

Closure fixes further_execution_authorized=false and acp_mutation_executed=false.

## Security boundary

This contract provides durable exact binding, expiry, and replay resistance for the authorization token. It does not authenticate the human/operator identity that requested issuance, attest the external executor binary, secure the transport used by that executor, eliminate filesystem TOCTOU, prove causal attribution, or provide a mutation executor.

## Current frontier

The ACP remote-mutation control stack now has candidate contracts for authority admission, transaction planning, exact-plan composition, path safety, rollback custody, durable journal/recovery, explicit single-use execution authorization, read-only postcondition verification, execution/result-evidence binding, and authorization-to-evidence closure.

Live repository mutation by ACP itself remains NOT IMPLEMENTED. Any future executor must be a separate tranche and must consume this exact authorization before recording execution intent and performing a side effect.