# Remote Mutation Composition Candidate

Status: **NON-EXECUTING / PLAN-SUBSTITUTION DEFENSE**.

This tranche composes the mutation authority-admission record with the exact
prepared transaction plan. It exists to prevent an admitted intent from being
followed by a different request, authority, resource, operation, or plan.

## Composition requirements

The composed record requires agreement across:

- request ID;
- authority ID;
- resource ID/type;
- operation ID;
- canonical plan SHA-256;
- prepared transaction identity;
- verified preconditions;
- available rollback identity.

Any mismatch is BLOCKED.

## Strong non-effect

The composed record always fixes:

```text
execution_enabled=false
mutation_executed=false
```

An admitted composition means only that authority admission and the exact
prepared transaction are congruent. It does not authorize or perform mutation.

## Remaining gates

The next candidate gate applies operation-specific path/symlink/repository-metadata defenses to the exact admitted plan while keeping execution disabled. After that, ACP still needs rollback-material custody, postcondition verification, crash/interruption recovery, execution receipts/result-evidence binding, and a separate explicit mutation-execution authorization gate.
