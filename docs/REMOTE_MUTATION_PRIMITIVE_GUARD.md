# Remote Mutation Primitive-Entry Guard

Status: **EXPERIMENTAL HARDENING / DOES NOT ELIMINATE TOCTOU**.

## Reproduced failure mode

A Windows temporary-repository audit demonstrated a concrete parent-directory race:

1. path safety passed for `repo/docs/example.md`;
2. the `docs` directory was renamed;
3. a junction named `docs` was created pointing outside the repository;
4. the pre-hardening write primitive followed that new parent path and wrote outside the repository.

The original repository file remained unchanged, proving that repeated path checks outside the primitive did not bind the later filesystem operation to the previously inspected directory object.

## Mitigation in this tranche

The executor now runs a primitive-level guard:

- immediately on entry to the write/delete primitive;
- again immediately before `os.replace` for writes.

The guard rechecks:

- lexical containment beneath the already allowlisted resolved repository root;
- resolved target containment;
- symlink / Windows reparse-point ancestors;
- symlink / reparse target state;
- existing multi-hardlink target state.

The full executor regression includes a race injection after the second normal path-safety validation but before the primitive call. The swapped junction is rejected, no outside write occurs, the consumed authorization remains non-replayable, the journal enters FAILED, and recovery holds conservatively.

## Residual boundary

This does **not** eliminate TOCTOU. A hostile concurrent actor may still race after the final primitive guard but before the kernel applies `os.replace` or `unlink`, or may interfere with the temporary-path name after creation.

A stronger hostile-local-actor guarantee requires a handle-bound/object-capability design in which the operation is applied relative to already-opened trusted directory/file handles rather than path strings that are re-resolved later.

Issue #117 remains the implementation tracker for that stronger design.

## Evidence boundary

All race reproduction and mitigation tests use disposable temporary repositories. No real ACP, DGAF, Aetherwake, or other project repository is used by this tranche.
