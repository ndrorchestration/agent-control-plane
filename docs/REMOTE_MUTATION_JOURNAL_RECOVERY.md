# Remote Mutation Journal and Recovery

Status: **DURABLE CONTROL/EVIDENCE JOURNAL / NON-EXECUTING**.

This tranche adds a SQLite-backed append-only journal around the remote mutation control path. The journal records control and evidence state for an external mutation workflow; it does not write, delete, rename, or otherwise mutate the target repository.

## Journal identity

A transaction begins only after exact path-safety and rollback-custody admission. The journal binds transaction ID, request/resource/operation identity, canonical plan SHA-256, rollback descriptor SHA-256, custody reference, and canonical UTC creation time.

Duplicate transaction IDs are idempotent only when every bound field matches exactly. Drift fails closed.

## State machine

Allowed states are prepared, execution_intent_recorded, external_effect_reported, postcondition_verified, rollback_intent_recorded, rollback_verified, and failed.

Evidence SHA-256 is mandatory for external-effect, postcondition-verified, and rollback-verified states. Failed events require an error description. Terminal states reject later appends.

## Recovery dispositions

- SAFE_PRE_EXECUTION: only prepared state exists; no execution intent was recorded.
- HOLD_AMBIGUOUS_EFFECT: execution intent was recorded but effect state is unknown.
- HOLD_POSTCONDITION_REQUIRED: an external effect was reported but exact postcondition verification is still missing.
- CLEAN_POSTCONDITION_VERIFIED: exact postcondition evidence was recorded.
- HOLD_ROLLBACK_AMBIGUOUS: rollback intent was recorded but rollback outcome is unknown.
- CLEAN_ROLLED_BACK: rollback verification evidence was recorded.
- FAILED_PRE_EXECUTION: failure occurred before execution intent.
- HOLD_FAILED_AFTER_EXECUTION_INTENT: failure occurred after execution intent and repository mutation may exist.

Every recovery assessment fixes new_execution_authorization_required=true. Recovery classification never reuses or fabricates execution authority.

## Strong non-effects

The journal persists only ACP control/evidence metadata. It does not execute a mutation, authorize execution, perform rollback, prove who caused an observed state transition, authenticate external evidence, or establish production-grade tamper resistance.

## Remaining gates

Before a live ACP mutation path can be considered, the stack still needs execution receipt/result-evidence binding and a separate explicit live mutation-execution authorization gate. Any future executor must compose journal intent recording before side effects and postcondition/rollback evidence after side effects in a way appropriate to the final threat model.