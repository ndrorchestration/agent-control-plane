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


## Windows handle-mutation synthetic probe

A second Windows-only synthetic probe verifies two concrete properties without
touching any real project repository:

1. opening an existing target without `FILE_SHARE_DELETE` prevents pathname
   replacement while that handle remains open;
2. `SetFileInformationByHandle(FileDispositionInfo)` can delete the exact
   opened synthetic file by handle.

Local Windows verification:

- handle identity + synthetic handle mutation + executor/recovery tests:
  36 PASS / 1 skipped.

This materially reduces uncertainty for delete semantics.

### Remaining write/replace problem

Existing-file replacement is harder than deletion because ACP currently wants
both:

- object-bound protection against target substitution; and
- atomic replacement semantics.

Keeping a target handle open without delete sharing blocks replacement by any
actor, including ACP's own pathname-based replacement. Closing that handle
before `os.replace` restores the race window.

A future Windows design therefore needs a deliberate choice, such as:

- handle-bound in-place write/truncate with explicit crash-recovery semantics;
- a handle-relative rename/replace design using a trusted parent directory
  handle and carefully verified Windows rename semantics;
- or retention of pathname atomic replacement with an explicit residual TOCTOU
  ceiling.

Do not treat the successful delete probe as proof that write replacement is
solved.

```text
HANDLE_BOUND_DELETE_FEASIBILITY=VERIFIED_SYNTHETIC_WINDOWS
TARGET_REPLACEMENT_BLOCK_BY_OPEN_HANDLE=VERIFIED_SYNTHETIC_WINDOWS
HANDLE_BOUND_ATOMIC_WRITE_REPLACEMENT=NOT_ESTABLISHED
REAL_PROJECT_REPOSITORY_EXECUTION=NOT_AUTHORIZED
```


## Win32 rename finding

The synthetic Windows probe produced an important API-specific result:

- `SetFileInformationByHandle(FileRenameInfo)` with an absolute destination
  path and `RootDirectory=NULL`: PASS in the disposable probe;
- `SetFileInformationByHandle(FileRenameInfo)` with a held parent-directory
  handle in `RootDirectory` and a relative target name: reproducible
  `ERROR_INVALID_PARAMETER (87)` on this Windows host.

This conflicts with the documented `FILE_RENAME_INFO.RootDirectory` contract
for the tested Win32 entrypoint. The failing relative-handle test is retained as
a strict expected failure so this limitation stays visible.

The implication for #117 is:

- handle-derived object identity is locally verified;
- holding an object without delete-sharing blocks pathname substitution;
- handle-based delete via `FileDispositionInfo` is locally verified;
- source-handle atomic rename with an absolute destination path is locally
  verified;
- parent-directory-handle-relative rename is **not** established via
  `SetFileInformationByHandle` on this host.

A lower-level Windows API path may be required if parent-directory anchoring is
a hard requirement. That path is not yet part of ACP and must be evaluated
separately before any assurance promotion.

```text
WIN32_ABSOLUTE_HANDLE_RENAME=VERIFIED_SYNTHETIC_WINDOWS
WIN32_ROOTDIRECTORY_RELATIVE_RENAME=NOT_ESTABLISHED_ERROR_87
LOWER_LEVEL_HANDLE_RELATIVE_RENAME=NOT_EVALUATED_IN_ACP
```


## NT-native handle-relative rename feasibility

A disposable Windows probe now exercises `NtSetInformationFile` with
`FileRenameInformation`, a held source handle, and a held destination-parent
directory handle.

Local results:

- NT-native parent-handle-relative atomic replacement: PASS;
- returned NTSTATUS: `0x00000000`;
- destination content replaced with prepared content: PASS;
- prepared source removed after successful rename: PASS;
- attempted pathname rename of the held trusted parent: blocked with
  `WinError 5 / Access is denied`;
- focused handle-identity / mutation / executor suite:
  **22 PASS / 1 skipped / 1 expected Win32 failure**.

The expected failure remains the higher-level
`SetFileInformationByHandle(FileRenameInfo)` + non-NULL `RootDirectory`
path. It is retained as negative API evidence rather than deleted.

This establishes a viable lower-level Windows primitive for synthetic
handle-relative replacement. It does **not** yet establish that ACP's live
executor correctly composes that primitive with authorization consumption,
durable intent, rollback custody, postcondition verification, and recovery.

```text
NT_NATIVE_HANDLE_RELATIVE_RENAME=VERIFIED_SYNTHETIC_WINDOWS
HELD_PARENT_PATHNAME_SWAP=BLOCKED_IN_SYNTHETIC_TEST
ACP_EXECUTOR_HANDLE_BOUND_WRITE_INTEGRATION=NOT_IMPLEMENTED
FINAL_TOCTOU_ELIMINATION=NOT_ESTABLISHED
REAL_PROJECT_REPOSITORY_EXECUTION=NOT_AUTHORIZED
HIGH_ASSURANCE=NOT_AUTHORIZED
```

The next admissible #117 step is to extract the NT-native primitive behind a
narrow Windows-only adapter and test it against disposable repository fixtures
through the executor's existing authorization/journal/recovery lifecycle.


## NT handle-relative rename feasibility — 2026-09-27

A lower-level Windows synthetic probe now exercises
`NtSetInformationFile(FileRenameInformation)` with:

- a source file held by handle;
- a destination parent directory held by handle;
- a relative destination filename;
- disposable pytest temporary directories only.

Focused local verification on Windows / Python 3.12:

- Win32 open-handle substitution blocking: PASS;
- handle-based delete: PASS;
- Win32 `SetFileInformationByHandle` + non-NULL `RootDirectory`: retained strict XFAIL (ERROR_INVALID_PARAMETER / 87);
- Win32 source-handle absolute rename: PASS;
- NT `NtSetInformationFile(FileRenameInformation)` parent-handle-relative replace: PASS;
- NT parent-handle-relative rename while the held parent prevents pathname displacement: PASS.

Focused mutation-probe result: **5 PASS / 1 expected failure**.
Combined focused identity/mutation/executor suite: **20 PASS / 1 skipped / 1 expected failure**.

Microsoft's published filesystem semantics describe `FileRenameInformation`
with a nonzero `RootDirectory` as resolving the destination relative to that
directory for local operations. This supports the semantics exercised by the
probe, but ACP's use of the lower-level NT entrypoint remains an experimental
platform-specific implementation direction rather than a portable contract.

Assurance ceiling remains:

```text
NT_HANDLE_RELATIVE_RENAME=VERIFIED_SYNTHETIC_LOCAL_WINDOWS
WIN32_ROOTDIRECTORY_RELATIVE_RENAME=NOT_ESTABLISHED_ERROR_87
HANDLE_BOUND_ATOMIC_WRITE_REPLACEMENT_IN_EXECUTOR=NOT_IMPLEMENTED
CROSS_WINDOWS_VERSION_FILESYSTEM_VALIDATION=NOT_ESTABLISHED
REAL_PROJECT_REPOSITORY_EXECUTION=NOT_AUTHORIZED
HIGH_ASSURANCE=NOT_AUTHORIZED
```

Next admissible engineering step: isolate the NT primitive behind a narrow
Windows adapter and test it only against disposable local filesystem fixtures,
including target-exists, target-missing, parent/object substitution attempts,
same-volume enforcement, and fail-closed error handling. Do not wire it into
real repository execution until those adapter tests and #118 process-boundary
requirements are separately satisfied.
