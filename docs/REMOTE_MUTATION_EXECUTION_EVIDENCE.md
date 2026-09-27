# Remote Mutation Execution Evidence Binding

Status: **NON-EXECUTING / RESULT-EVIDENCE BINDING ONLY**.

This tranche binds caller-supplied external execution evidence to the exact ACP mutation plan, durable journal transaction, external-effect evidence, and verified postcondition. It does not authenticate the external executor and does not authorize mutation execution.

## Required congruence

The binder requires exact agreement across transaction ID, request/resource/operation identity, canonical plan SHA-256, rollback descriptor SHA-256, rollback custody reference, one journal external-effect event, terminal postcondition-verified journal state, and one verified postcondition record. The stronger postcondition identity must match both the exact plan rollback hash and the journal's bound custody chain.

The caller-supplied evidence carries executor ID, execution ID, result SHA-256, external-effect evidence SHA-256, and postcondition-evidence SHA-256. The complete evidence object has deterministic canonical bytes and its own SHA-256 content identity.

## Strong non-effects

Every receipt fixes execution_authorized=false and acp_mutation_executed=false. A bound receipt means only that the supplied identities and hashes are congruent with the accepted ACP evidence chain.

It does not establish executor authenticity, transport authenticity, independent custody, causal attribution, code signing, production security, or permission to perform another mutation.

## Remaining gate

The mutation stack is now complete through non-executing authority admission, transaction planning, exact-plan composition, path safety, rollback custody evidence, postcondition verification, crash/recovery journaling, and execution/result-evidence binding.

A separate durable single-use execution-authorization contract now binds one named external executor to one exact prepared transaction and prevents replay through persistent consumption state. A closure record then binds the consumed authorization to the terminal execution-evidence chain. ACP itself still has no repository mutation executor; any future executor must be a separate implementation tranche.