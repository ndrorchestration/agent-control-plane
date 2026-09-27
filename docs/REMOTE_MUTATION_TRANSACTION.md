# Remote Mutation Transaction Candidate

Status: **NON-EXECUTING / TRANSACTION-MODEL ONLY**.

This tranche follows remote mutation authority admission and deliberately stops
before live mutation execution.

## Fixed operation registry

The candidate registry is immutable at runtime and initially contains only:

- `repo.write_text_file`
- `repo.delete_file`

Adding an operation is a capability expansion and therefore requires source-code
change plus tests. Callers cannot supply arbitrary shell text or argv.

## Transaction bindings

A `MutationPlan` binds:

- request ID;
- authority ID;
- resource ID/type;
- exact operation ID;
- exact structured parameters;
- expected precondition SHA-256;
- expected rollback SHA-256;
- canonical plan SHA-256.

`prepare_mutation_transaction(...)` compares observed precondition and rollback
identities with the plan. Drift blocks the transaction.

## Strong non-effects

Every transaction receipt fixes:

```text
mutation_executed=false
execution_enabled=false
```

`PRECONDITIONS_VERIFIED` means only that the declared precondition and rollback
identities matched. It is not permission or capability to perform the mutation.

## Still required before execution can be considered

- compose mutation admission with transaction-plan identity;
- define exact filesystem/repository precondition capture semantics;
- define creation/update/delete rollback material and custody;
- add postcondition verification semantics;
- define crash/interruption journal and recovery behavior;
- bind result evidence to execution identity and authority decision;
- independently review operation-specific path/symlink/metadata hazards;
- explicitly authorize a live executor in a separate gate.
