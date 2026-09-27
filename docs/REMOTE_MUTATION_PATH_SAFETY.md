# Remote Mutation Path Safety

Status: **NON-EXECUTING / PATH-SAFETY ADMISSION ONLY**.

This tranche follows exact authority + transaction-plan composition. It inspects the repository path bound into that exact plan and produces a fail-closed safety record before any live mutation executor exists.

## Preconditions

`inspect_repository_mutation_path(...)` requires:

- an already-admitted `MutationCompositionRecord`;
- the exact `MutationPlan` bound by that composition;
- an absolute local repository root with a `.git` marker.

If the composition does not match the exact request/resource/operation/plan hash, path safety is blocked before filesystem admission.

## Canonical repository path rules

Mutation paths are repository-relative and must use one canonical `/` spelling. The candidate rejects absolute or drive-qualified paths, `.` / `..` / empty segments, backslashes, control characters, NTFS ADS `:` syntax, ambiguous leading/trailing spaces or trailing dots, Windows reserved device names, and any case-insensitive `.git` segment.

`MutationPlan` preserves the exact `path` string instead of trimming it before canonical plan hashing. This prevents path spelling from changing between plan identity and path-safety inspection.

## Read-only filesystem checks

The inspector verifies that the resolved target remains inside the resolved repository root; that root/ancestors/target are not symlinks or Windows reparse points; that an existing file target has no additional hardlink names; that repository metadata is not targeted; that `repo.write_text_file` has an existing directory parent and does not target a directory; and that `repo.delete_file` targets an existing regular file.

The candidate does not create, write, rename, or delete anything during inspection.

## Strong non-effects

Every `MutationPathSafetyRecord` fixes `execution_enabled=false` and `mutation_executed=false`. Path admission is not mutation authorization and is not execution.

## Known boundaries

The next candidate gate binds deterministic rollback material to an opaque custody/read-back evidence reference while keeping execution disabled. This path-safety candidate itself does not establish rollback-material custody, postcondition verification, crash/interruption recovery, execution receipts/result-evidence binding, cross-machine filesystem identity, complete Windows reparse/device semantics beyond the current attribute + resolved-boundary checks, a live mutation executor, or explicit mutation-execution authorization. Hardlink targets are now rejected when the current filesystem reports more than one link.
