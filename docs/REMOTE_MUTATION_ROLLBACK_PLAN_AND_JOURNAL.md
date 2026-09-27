# Explicit Repository Rollback Plan and Journal

Status: **NON-EXECUTING / NON-AUTHORIZING ROLLBACK FOUNDATION**.

## Why rollback is a separate transaction

The canonical mutation journal intentionally treats `FAILED` as terminal. A failed execution must not have its historical evidence rewritten or reopened merely to perform recovery.

Therefore rollback is modeled as a new governed transaction linked to the original mutation transaction.

The original journal remains immutable.

## Rollback plan

`RepositoryRollbackPlan` binds:

- a new rollback request, authority, and transaction ID;
- original transaction/request/resource/operation identity;
- original mutation plan SHA-256 and original terminal/current journal state;
- exact rollback descriptor SHA-256 and custody reference;
- exact repository-relative path;
- typed rollback action: restore prior file bytes or delete the created file;
- explicit expected current target existence/content hash;
- exact desired rollback postcondition.

The plan fixes `execution_enabled=false` and `rollback_executed=false`.

Recovery rollback planning requires evidence that original execution intent was durably recorded. A PREPARED-only/pre-execution failure is not rollback-eligible. A successfully postcondition-verified mutation is also excluded from this recovery-rollback contract; deliberate later reversal is a different governed operation.

## Current-state safety

The plan binds an explicit current-state expectation. A future rollback executor must re-observe and match that exact state immediately before rollback. If concurrent changes cause target existence/content to differ, rollback must fail closed rather than overwrite the changed state.

This tranche does not yet implement that filesystem revalidation or side effect.

## Separate durable rollback journal

`RemoteMutationRollbackJournal` stores a new rollback transaction linked to the original transaction and plan identities.

States:

- PREPARED
- ROLLBACK_INTENT_RECORDED
- ROLLBACK_EFFECT_REPORTED
- ROLLBACK_VERIFIED
- FAILED

Recovery distinguishes safe pre-rollback, ambiguous rollback, effect awaiting postcondition, clean verified rollback, pre-rollback failure, and failure after rollback intent.

Every recovery assessment requires a new rollback authorization before another effect.

## Remaining gates before any rollback side effect

1. rollback-specific path/current-state inspection;
2. explicit rollback authorization separate from original execution authority;
3. custody material retrieval/readback at execution time;
4. bounded rollback executor;
5. exact rollback postcondition verification;
6. rollback effect/evidence binding and closure;
7. crash/restart tests around the real rollback side-effect primitive;
8. synthetic/temp repositories only until separately authorized.

Automatic rollback remains prohibited.
