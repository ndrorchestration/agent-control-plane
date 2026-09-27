# Handle-Bound Filesystem Feasibility — Windows

Status: **DESIGN FINDING / NO NEW EXECUTION AUTHORITY**.

## Local capability probe

On the current Windows development host with Python 3.14.5:

- `os.supports_dir_fd` is empty;
- `os.O_NOFOLLOW` is unavailable;
- `os.O_DIRECTORY` is unavailable;
- `os.O_PATH` is unavailable.

Although Python exposes `dir_fd` parameters in several function signatures, the runtime capability set does not support directory-handle-relative operations on this platform.

## Consequence

The current Python path-level executor can narrow TOCTOU with repeated checks and the primitive-entry guard in PR #123, but it cannot establish a stable directory/file object capability across the final validation-to-effect interval.

Additional `Path.resolve()`, `stat`, or reparse checks would still re-resolve names and therefore cannot eliminate a hostile concurrent parent/path swap.

## Required stronger design

For a hostile-local-actor / High-Assurance filesystem identity claim on Windows, use an implementation that binds operations to already-opened kernel objects. Candidate directions for a dedicated design spike include:

1. Win32 file/directory handles opened with reparse-aware flags and identity verification;
2. NT native relative-object operations using a trusted directory handle as the root;
3. a minimal signed/native helper exposing only the two typed operations ACP requires, with no shell/argv surface.

Any native helper must preserve the existing ACP gates:

- exact repository-root allowlist;
- canonical repository-relative path;
- .git exclusion;
- rollback/current-state preconditions;
- single-use authorization;
- durable intent before effect;
- postcondition/evidence/closure;
- recovery on interruption.

## Non-goals

This finding does not justify broad native command execution, shell access, recursive mutation, or a general filesystem broker.

## Current boundary

PR #123 remains a bounded path-level mitigation that blocks the reproduced junction-swap placement. Issue #117 remains open for the native handle-bound design/implementation needed to claim stronger object identity.
