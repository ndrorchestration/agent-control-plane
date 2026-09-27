# Experimental Repository Mutation Executor Candidate

Status: **EXPERIMENTAL / LIVE SIDE EFFECTS DISABLED BY DEFAULT**.

This is the first ACP candidate capable of changing repository file state. It remains isolated from main and requires explicit construction with `experimental_enable=True` plus an exact allowlist of repository roots.

## Supported operations

Only the typed operation registry's current file operations are implemented:

- `repo.write_text_file`
- `repo.delete_file`

There is no shell, argv, command-string, arbitrary process, recursive-delete, rename, chmod, or repository-metadata mutation surface.

## Mandatory execution sequence

1. Repository root must exactly match an allowlisted resolved root and contain a `.git` marker.
2. Path safety is revalidated against the exact admitted plan.
3. Rollback descriptor and current file-state preconditions are revalidated.
4. Operation input is validated before authorization consumption; invalid bytes do not burn the token.
5. The exact #108-style authorization is atomically consumed.
6. `EXECUTION_INTENT_RECORDED` is durably appended before any side effect.
7. Path safety and rollback preconditions are revalidated again immediately before the side effect.
8. Write uses same-directory temporary bytes, flush + fsync, then `os.replace`; delete uses only exact-file `unlink`.
9. External-effect evidence is journaled.
10. Read-only postcondition verification must match the exact plan.
11. Postcondition evidence, execution-evidence binding, and authorization closure must all succeed.

## Fail-closed behavior

Pre-consumption input/path/content drift leaves the authorization unused and journal `PREPARED`.

A crash after durable authorization consumption but before `EXECUTION_INTENT_RECORDED` leaves the token consumed while the journal is still `PREPARED`. The cross-store recovery assessor recognizes this exact combination as **no repository side effect possible under this executor ordering, but reauthorization required**. Once execution intent is durably recorded, any failure before verified postcondition/rollback evidence is treated as potentially mutated and requires a recovery hold. The executor does not silently retry and does not auto-rollback.

## Current evidence boundary

Development tests execute side effects only inside temporary synthetic repositories created by pytest. This tranche has not been exercised against the user's real ACP, DGAF, Aetherwake, or other project repositories.

## Known unresolved boundaries

- no automatic rollback executor;
- filesystem TOCTOU is reduced by repeated checks but not eliminated;
- hardlink equivalence is not detected;
- Windows reparse-point policy is limited to the current path-resolution/symlink checks;
- executor binary/process authenticity is not attested;
- transport authenticity is not established;
- no OS sandbox, privilege separation, or production security certification;
- no DGAF High-Assurance authorization;
- no independent validation.

Do not merge or treat this candidate as production authorization merely because temporary-repository tests pass.