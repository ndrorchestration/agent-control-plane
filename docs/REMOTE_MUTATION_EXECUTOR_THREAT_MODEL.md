# Remote Mutation Executor Threat Model

Status: **REVIEW CONTRACT / DOES NOT AUTHORIZE REAL-REPOSITORY EXECUTION**.

## Scope

This document defines the security and recovery assumptions for the bounded ACP repository mutation executor. The executor supports only `repo.write_text_file` and `repo.delete_file`, is disabled by default, and has been exercised only against pytest-created temporary repositories.

## Protected assets

- repository contents and repository metadata;
- exact mutation-plan identity and authority binding;
- rollback-material identity and custody reference;
- single-use execution authorization state;
- durable mutation journal and postcondition/evidence chain;
- operator ability to distinguish no-effect, ambiguous-effect, verified-effect, and rollback states after interruption.

## Explicitly untrusted or partially trusted inputs

- caller-supplied repository path strings before canonicalization;
- repository filesystem state that can drift after admission;
- caller-supplied execution/result evidence until bound to exact ACP records;
- stale process memory after restart;
- external actors capable of changing files/directories concurrently.

## Current trusted computing base

- the Python interpreter and ACP process executing the candidate;
- the OS filesystem APIs used by `os.replace`, `unlink`, `stat/lstat`, and SQLite;
- the local OS account permissions under which the executor runs;
- SQLite durability/locking for each individual store;
- the configured exact repository-root allowlist.

These are assumptions, not independently attested facts. ACP currently does not attest the executor binary/process, isolate it in a sandbox, or cryptographically authenticate the local OS execution environment.

## Safety invariants

1. No side effect occurs unless the exact plan, path safety, rollback custody, prepared journal, and single-use authorization all agree.
2. Invalid operation input, path drift, rollback drift, or authorization mismatch fails before the side effect.
3. Durable execution intent is recorded before the executor calls the side-effect primitive.
4. Existing multi-hardlink targets, symlink targets/ancestors, and Windows reparse-point targets/ancestors fail closed at each path inspection.
5. A successful execution is not complete until exact postcondition verification, execution-evidence binding, and authorization closure succeed.
6. Any recovery path requires a fresh authorization decision before another effect.
7. At or after durable execution intent, missing terminal evidence is treated as potentially mutated.

## Residual race boundary

The final path/rollback inspection and the later `os.replace` / `unlink` call are separate filesystem operations. A concurrent actor with sufficient filesystem privileges can attempt to change an ancestor or target between those operations. Repeated validation narrows this interval but cannot prove stable filesystem object identity across the interval.

For stronger identity guarantees against a hostile concurrent filesystem actor, the design should use platform primitives that bind operations to already-opened directory/file handles (or an equivalent OS-enforced capability) rather than re-resolving path strings. On Windows this requires an explicit Win32 handle-based design review; Python path-level checks alone are not sufficient to claim elimination of TOCTOU.

Therefore: **residual TOCTOU remains a blocker for High-Assurance claims, but not evidence that the current temp-repository candidate is functionally incorrect under its present cooperative-local-filesystem threat model.**

## Cross-store atomicity decision

Authorization consumption and journal intent are currently durable in separate SQLite stores. They cannot commit atomically as one transaction. The fixed executor ordering is:

`validate -> consume authorization -> append EXECUTION_INTENT_RECORDED -> revalidate -> side effect`

This creates one intentional coordination window: authorization may be consumed while the journal remains PREPARED. Under the current executor implementation no repository side effect is invoked before journal intent, so cross-store recovery can classify this exact persisted combination as **no effect possible / fresh authorization required**.

The reverse combination—journal advanced beyond PREPARED while the authorization is unconsumed—is impossible under the intended executor ordering and is held as divergence.

Conclusion: a single atomic store is **not required for fail-closed safety under the fixed current ordering**, because every crash-visible combination has a conservative recovery classification. A shared transaction or unified store would still be required for a stronger exactly-once/linearizable coordination claim and may simplify auditing.

## Process identity and OS isolation boundary

The executor currently relies on application-level `executor_id` binding, not cryptographic or OS-backed process identity. A process running with the same local permissions and direct access to the SQLite stores or repository may bypass ACP entirely.

Before any production or High-Assurance claim, evaluate:

- a trusted launcher or signed/attested executable boundary;
- least-privilege service identity with repository access limited to authorized roots;
- ACL separation for authorization/journal stores and repository roots;
- sandboxing or job/process restrictions appropriate to Windows;
- protection against direct store tampering by peer processes.

## Rollback boundary

Rollback material is admitted and custody-bound, but the executor does not automatically roll back. This is intentional. Automatic rollback after an ambiguous crash can itself destroy evidence or overwrite valid concurrent changes.

A future rollback executor must be a separate explicitly authorized operation with its own path revalidation, current-state precondition, journal intent, evidence, postcondition, and recovery semantics.

## Acceptance criteria before any real-project exercise

A real-project repository exercise remains blocked until all of the following are explicitly reviewed and accepted:

- this threat model is reviewed against the intended attacker/concurrency model;
- residual TOCTOU is either mitigated with handle-bound operations or explicitly accepted for a lower-assurance test lane;
- executor process identity / least-privilege boundary is defined;
- authorization/journal store ACL and tamper assumptions are documented;
- a disposable or dedicated test repository is selected; canonical ACP/DGAF/Aetherwake working repositories are not the first target;
- backup/rollback custody is independently readable before execution;
- operator stop/recovery procedure is tested;
- one exact operation and one exact file are authorized; no wildcard or recursive scope;
- post-execution evidence is reviewed before any second mutation.

## Current conclusion

The candidate has strong application-level fail-closed controls and durable recovery evidence for cooperative local execution, including crash/restart cases. It does **not** yet meet a High-Assurance hostile-local-actor threat model because filesystem object identity across the final TOCTOU window, process authenticity, OS isolation, and store tamper resistance are not established.