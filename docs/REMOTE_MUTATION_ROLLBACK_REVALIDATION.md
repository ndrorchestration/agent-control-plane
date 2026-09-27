# Repository Rollback Current-State Revalidation

Status: **READ-ONLY / NON-EXECUTING / NON-AUTHORIZING**.

This gate follows the explicit rollback plan and separate rollback journal. It observes the exact repository target bound into a `RepositoryRollbackPlan` and checks whether the current filesystem state still matches the plan before any future rollback authorization could be considered.

## Exact checks

- repository root is absolute, exists, and retains a `.git` marker;
- rollback path spelling is preserved exactly in plan identity and must be canonical;
- resolved target remains within the resolved repository root;
- no case-insensitive `.git` segment is targeted;
- root/ancestors/target are not symlink or Windows reparse-point paths;
- existing file targets must not have multiple hardlink names;
- target parent exists as a normal directory;
- target existence matches `expected_current_target_exists`;
- if the target is expected to exist, its observed SHA-256 must equal `expected_current_content_sha256`.

Concurrent creation, deletion, or content drift therefore blocks rollback admission instead of overwriting the changed state.

## Strong non-effects

Every record fixes:

- `execution_enabled=false`
- `rollback_executed=false`

This module does not retrieve rollback bytes, grant rollback authority, write/delete files, append rollback intent, or execute rollback.

## Remaining rollback gates

1. separate single-use rollback authorization;
2. custody object retrieval/readback immediately before any effect;
3. bounded rollback executor;
4. exact rollback postcondition verification;
5. rollback effect/evidence binding and closure;
6. crash/restart tests around any future side-effect primitive;
7. synthetic/temp repositories only until separately authorized.

Automatic rollback remains prohibited.
