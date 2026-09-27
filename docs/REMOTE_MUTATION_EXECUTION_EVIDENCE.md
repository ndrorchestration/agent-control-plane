# Remote Mutation Execution Evidence Binding

Status: **NON-EXECUTING / RESULT-EVIDENCE BINDING ONLY**.

This tranche binds caller-supplied external execution evidence to the exact ACP mutation plan, durable journal transaction, external-effect evidence, and verified postcondition. It does not authenticate the external executor and does not authorize mutation execution.

## Required congruence

The binder requires exact agreement across transaction ID, request/resource/operation identity, canonical plan SHA-256, one journal external-effect event, terminal postcondition-verified journal state, and one verified postcondition record.

The caller-supplied evidence carries executor ID, execution ID, result SHA-256, external-effect evidence SHA-256, and postcondition-evidence SHA-256. The complete evidence object has deterministic canonical bytes and its own SHA-256 content identity.

## Strong non-effects

Every receipt fixes execution_authorized=false and acp_mutation_executed=false. A bound receipt means only that the supplied identities and hashes are congruent with the accepted ACP evidence chain.

It does not establish executor authenticity, transport authenticity, independent custody, causal attribution, code signing, production security, or permission to perform another mutation.

## Remaining gate

The mutation stack is now complete through non-executing authority admission, transaction planning, exact-plan composition, path safety, rollback custody evidence, postcondition verification, crash/recovery journaling, and execution/result-evidence binding.

A live mutation path remains NOT AUTHORIZED. The next required gate is a separate explicit live mutation-execution authorization design that composes these records without allowing stale authority, replay, plan substitution, path drift, missing rollback custody, unjournaled side effects, or unverified postconditions.