# Executor Filesystem Object Identity Hardening

Status: **EXPERIMENTAL / LIVE EXECUTOR STILL NOT ACCEPTED**.

This tranche addresses issue #117 by narrowing the pathname time-of-check/time-of-use
window in the bounded repository mutation executor.

## Threat model

Assume a local peer process can race the executor by replacing the target file
or its parent directory after authorization has been consumed but before the
filesystem side effect occurs.

The existing executor already performs:

- exact repository-root allowlisting;
- repository-relative path validation;
- .git / reserved-name / ADS rejection;
- symlink/reparse-point rejection;
- hardlink rejection;
- rollback-precondition revalidation;
- a second path-safety check immediately before the side effect.

The residual weakness is that those checks and the later `os.replace` /
`unlink` call are separate path-based operations.

## Added object-identity drift detection

Before consuming the single-use authorization, ACP snapshots:

- the target parent directory object identity;
- the target object identity, or explicit non-existence for a create.

Immediately before the side effect, after the second path and rollback
validation, ACP re-captures both identities and fails closed if:

- the parent existence changes;
- the parent device/inode/mode identity changes;
- the target existence changes;
- the target device/inode/mode identity changes.

On Windows this uses the object identity exposed by Python `os.stat(...,
follow_symlinks=False)`. On other supported runtimes it uses the equivalent
`st_dev` / `st_ino` values exposed by Python.

A detected swap occurs after authorization consumption and execution-intent
recording, so ACP does **not** retry automatically. The journal enters the
existing failed/ambiguous-effect recovery path.

## Evidence

Focused executor + recovery tests:

- 30 PASS.

Adversarial tests explicitly model:

- parent-directory object replacement after authorization;
- target-file object replacement after authorization.

Both must leave the original target contents unchanged while consuming the
authorization and forcing recovery-hold semantics.

## Assurance ceiling

This is a **drift detector**, not a handle-bound object capability.

It does not eliminate the final interval between the last identity check and
the later path-based `os.replace` / `unlink` syscall. A hostile local actor
with sufficient filesystem access may still race inside that interval.

Therefore:

```text
FILESYSTEM_OBJECT_IDENTITY_HARDENING=IMPROVED_BUT_NOT_HANDLE_BOUND
FINAL_PATH_TO_SYSCALL_TOCTOU=NOT_ELIMINATED
HIGH_ASSURANCE=NOT_AUTHORIZED
REAL_PROJECT_REPOSITORY_EXECUTION=NOT_AUTHORIZED
```

## Next #117 decision

For higher assurance, evaluate a platform-specific handle-bound design that
keeps a trusted parent-directory/file handle (or equivalent object capability)
through the effect operation. If the platform/runtime cannot provide such
semantics portably, retain this residual risk explicitly rather than promoting
the executor to High-Assurance.


## Windows handle-identity feasibility spike

A Windows-only read-only probe now uses:

- `CreateFileW` to open the exact existing filesystem object;
- `FILE_FLAG_OPEN_REPARSE_POINT` when requested so a reparse/symlink object can
  be opened without normal target traversal;
- `GetFileInformationByHandle` to record volume serial number + file index as
  handle-derived object identity.

Local Windows verification:

- stable file identity across reopen: PASS;
- stable directory identity across reopen: PASS;
- pathname replacement changes handle-derived identity: PASS;
- relative path rejection: PASS;
- reparse/symlink-object probe: SKIPPED because symlink creation was unavailable
  in this local environment;
- combined Windows-handle + executor/recovery suite: 34 PASS / 1 skipped.

This probe performs no mutation.

### Handle-bound implementation direction

The next stronger Windows executor design should keep trusted handles open across
the critical interval and use handle-based metadata operations where applicable.

Windows exposes `SetFileInformationByHandle` with file rename and disposition
information classes. A future prototype should evaluate:

1. open parent/target with reparse-safe flags and the minimum required rights;
2. record handle-derived object identity;
3. consume the exact single-use authorization;
4. record durable execution intent;
5. revalidate handle identity / current-state preconditions;
6. perform delete/rename semantics using handle-based Windows operations where
   possible rather than reopening by pathname;
7. verify the resulting state and evidence.

The current Python pathname executor is **not** automatically upgraded by this
probe.

```text
WINDOWS_HANDLE_IDENTITY_PROBE=VERIFIED_LOCAL_ENGINEERING
HANDLE_BOUND_MUTATION_EXECUTION=NOT_IMPLEMENTED
FINAL_TOCTOU_ELIMINATION=NOT_ESTABLISHED
HIGH_ASSURANCE=NOT_AUTHORIZED
```
