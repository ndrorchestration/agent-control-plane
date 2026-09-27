# Repository Rollback Authorization

Status: **AUTHORIZATION RECORD ONLY / NO ROLLBACK EXECUTOR**.

This gate creates a durable, exact, expiring, single-use authorization for one named rollback-executor identity and one exact `RepositoryRollbackPlan`.

## Issuance requirements

Authorization issuance requires:

- a non-executing rollback plan;
- an admitted rollback current-state/path revalidation record;
- exact plan/revalidation identity agreement;
- a separate rollback journal still in `PREPARED`;
- exact linkage to original transaction, original plan, rollback descriptor, and custody reference;
- explicit UTC issue and expiry times.

## Consumption

Consumption requires exact agreement on:

- authorization ID;
- rollback executor ID;
- rollback transaction ID;
- rollback-plan SHA-256;
- active time window.

Consumption is atomic in SQLite and single-use. Replay fails closed, including after reopening the store.

The authorization content hash deliberately excludes `consumed_at`, so the immutable authorization identity remains stable when consumption state is recorded.

## Strong non-effect

`rollback_executed=false` is fixed on the authorization record.

This module does not retrieve rollback material, append rollback intent, write/delete repository files, verify rollback postconditions, or authorize any other operation.

## Remaining rollback gates

1. custody material retrieval/readback at execution time;
2. bounded rollback executor;
3. exact rollback postcondition verification;
4. rollback effect/evidence binding and terminal closure;
5. crash/restart tests around the future rollback side-effect primitive.

Automatic rollback remains prohibited.
