# Windows Executor Deployment and Least-Privilege Boundary

Status: **DESIGN CONTRACT / NO SYSTEM CHANGES / NON-AUTHORIZING**.

## Problem

The current development setup runs ACP and repository work under the same local account, which has full control of the ACP repository. Application-level checks cannot stop another process under equivalent permissions from directly changing the repository or SQLite evidence stores.

A stronger execution boundary therefore requires OS-level separation, not only a better `executor_id`.

## Proposed deployment split

### Control-plane identity

The ACP decision/control process should:

- build and verify plans, authority, custody, journal/evidence contracts;
- have read access to repository state needed for evaluation;
- **not** require general write access to protected repository roots;
- produce one exact execution request/capability for the executor.

### Executor identity

A separate executor worker/service identity should:

- have write permission only to explicitly admitted repository roots;
- have no interactive shell or general command-execution interface;
- implement only the typed operations ACP authorizes;
- validate the exact plan/executor/process policy again;
- consume one execution capability;
- durably record intent before the side effect;
- return evidence/postcondition material.

This identity should not inherit broad administrator privileges.

## Windows account/ACL direction

For a stronger deployment, prefer a dedicated low-privilege local/service identity rather than the current interactive account.

Target ACL shape:

- repository root: executor identity gets only the minimum file permissions needed for typed operations; unrelated users/process identities do not inherit write access;
- authorization/journal state: writable only by the trusted control/executor boundary required by the selected protocol;
- rollback custody: executor gets read access only when rollback is explicitly authorized; ordinary mutation execution should not gain broader custody access;
- executable/helper installation directory: writable only by trusted installer/administrator identity, read/execute for executor identity;
- logs/evidence: append/create permissions without permission to rewrite prior accepted evidence where feasible.

Exact ACL commands are intentionally not applied by this tranche.

## Trusted launcher / binary identity

The SELF_REPORTED_LOCAL preflight in PR #124 is useful for drift detection but not attestation.

A stronger launcher should verify at least:

- expected executable/helper SHA-256;
- trusted installation path whose ACL prevents executor self-modification;
- expected service/user identity;
- executable signature or equivalent trusted deployment provenance where available;
- exact ACP executor protocol/schema version.

A native helper introduced for #117 handle-bound filesystem operations should be the smallest possible binary surface and should not expose shell, argv, arbitrary path, recursive, or generic filesystem capabilities.

## IPC boundary

If control plane and executor use separate identities, prefer a narrow local IPC protocol carrying typed fields rather than shared shell commands.

The request should bind:

- authorization ID;
- transaction ID;
- plan SHA-256;
- operation ID;
- repository-root identity;
- requested repository-relative path;
- expected current-state/rollback identity;
- expiry/single-use semantics.

The executor must reject any request not exactly congruent with its locally loaded authorization/evidence state.

## Job Objects / AppContainer

Windows Job Objects can constrain process lifetime/resource behavior but are not by themselves a filesystem authorization boundary.

AppContainer or a stronger sandbox may reduce ambient access, but repository access and SQLite/custody access would need deliberate capabilities/ACLs. It should be evaluated only after the simpler dedicated-identity + narrow-ACL design is specified and tested.

## Acceptance tests before stronger claims

A future implementation should prove, using a disposable repository and disposable OS identity/environment where practical:

1. the control-plane identity cannot directly write the protected repository;
2. the executor identity cannot write outside its exact admitted root;
3. an unrelated peer process cannot modify authorization/journal/custody state;
4. replacing the executor binary/hash causes preflight/admission failure;
5. running under the wrong user identity causes preflight/admission failure;
6. an expired/replayed capability is rejected;
7. process restart preserves consumed capability and recovery state;
8. no shell/argv/general filesystem operation is reachable through IPC;
9. evidence remains available if the executor crashes after intent;
10. all tests remain synthetic/disposable until separately authorized.

## Current conclusion

For the present local-development lane, PR #124 provides useful process drift detection only.

For a stronger production/High-Assurance claim, a dedicated low-privilege executor identity plus narrow ACL/IPC boundaries is the minimum practical next architecture. Job Objects/AppContainer are defense-in-depth candidates, not substitutes for permission separation.

No account, service, ACL, sandbox, or launcher is created by this document.
