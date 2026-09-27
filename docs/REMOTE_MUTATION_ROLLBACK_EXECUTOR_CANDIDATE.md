# Bounded Repository Rollback Executor Candidate

Status: **EXPERIMENTAL / LIVE SIDE EFFECTS DISABLED BY DEFAULT**.

This is the first rollback candidate capable of restoring or deleting repository file state. It is separate from the original mutation executor and from automatic rollback.

## Supported rollback actions

- `restore_file_bytes`
- `delete_created_file`

No shell, command string, recursive delete, rename, chmod, repository metadata mutation, or implicit rollback exists.

## Mandatory ordering

1. exact repository root must be allowlisted and still be a Git repository;
2. durable rollback authorization must exist, be unconsumed, and name this executor;
3. rollback journal must be `PREPARED`;
4. exact rollback current-state revalidation must pass;
5. current state must still match the earlier admitted revalidation record;
6. custody material readback identity must match;
7. authorization is consumed;
8. `ROLLBACK_INTENT_RECORDED` is durably appended;
9. current-state revalidation runs again immediately before the primitive;
10. restore uses same-directory temp bytes + flush/fsync + `os.replace`; delete uses exact-file `unlink`;
11. rollback effect evidence is journaled;
12. desired rollback postcondition must match exactly;
13. `ROLLBACK_VERIFIED` is journaled only after successful postcondition verification.

## Failure semantics

Failures before authorization consumption leave the token unused and the journal `PREPARED`.

Failures after consumption/intent consume the token permanently and leave durable recovery evidence. The executor never retries or auto-rolls back.

## Evidence boundary

Tests perform side effects only in pytest-created temporary repositories.

No ACP, DGAF, Aetherwake, or other real project repository is authorized for rollback execution by this candidate.

High-Assurance remains NOT ESTABLISHED / NOT AUTHORIZED.
