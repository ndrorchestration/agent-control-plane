# Remote Mutation Rollback Authorization

Status: **NON-EXECUTING / SEPARATE GOVERNED ACTION**.

This tranche addresses issue #119 by defining rollback as its own typed,
expiring, single-use authorization. It does not add a rollback executor.

## Why rollback is separate

Automatic rollback after an ambiguous mutation failure can destroy evidence or
overwrite legitimate concurrent changes. Rollback therefore requires a new
governance decision rather than inheriting the original forward authorization.

```text
FORWARD_MUTATION_AUTHORIZATION != ROLLBACK_AUTHORIZATION
ROLLBACK_AUTHORIZATION != ROLLBACK_EXECUTION
```

## Required bindings

A rollback authorization binds:

- distinct rollback authority ID;
- distinct rollback executor ID;
- original transaction/request/resource/operation identity;
- fixed rollback operation ID `repo.rollback`;
- original plan SHA-256;
- rollback descriptor SHA-256;
- rollback custody reference;
- exact current-state observation SHA-256;
- current rollback-eligible journal state;
- issue/expiry window;
- durable single-use consumption.

## Safe current-state rule

Rollback authorization is refused unless the current repository state still
matches the state that the original mutation was expected to create.

Examples:

- existing-file write rollback: target must still contain the exact planned
  post-write content before prior bytes could be restored;
- created-file rollback: the created target must still contain the exact planned
  content before deletion could be considered;
- delete rollback: the target must still be absent before prior bytes could be
  restored.

If another actor modifies or recreates the target, ACP refuses rollback rather
than overwriting the concurrent change.

## Journal eligibility

The current journal allows rollback intent only from ambiguous/nonterminal
effect states:

- `EXECUTION_INTENT_RECORDED`;
- `EXTERNAL_EFFECT_REPORTED`.

This authorization contract follows that state machine. It does not silently
make terminal states rollbackable.

A future change that permits rollback after another state must first modify and
test the recovery state machine explicitly.

## Strong non-effects

Every authorization fixes:

```text
execution_enabled=false
rollback_executed=false
```

This tranche does not:

- write or delete files;
- restore rollback bytes;
- append rollback intent automatically;
- verify a rollback postcondition;
- attribute a prior effect to ACP;
- establish production-safe recovery;
- authorize use against a real project repository.

## Next implementation gate

A future rollback executor must:

1. independently re-read the exact current state at consumption time;
2. consume this single-use rollback authorization before rollback intent;
3. append durable `ROLLBACK_INTENT_RECORDED` before any side effect;
4. apply only the descriptor-defined rollback operation;
5. verify the exact rollback postcondition;
6. append `ROLLBACK_VERIFIED` with evidence;
7. fail into an explicit ambiguous rollback recovery state on interruption;
8. preserve the original failed/ambiguous execution evidence.

Until that executor is separately designed, tested, and authorized:

```text
ROLLBACK_EXECUTION=NOT_ESTABLISHED
REAL_PROJECT_REPOSITORY_EXECUTION=NOT_AUTHORIZED
HIGH_ASSURANCE=NOT_AUTHORIZED
```
