# Executor Trusted Process Boundary

Status: **DESIGN + MACHINE-CHECKABLE ASSESSMENT / NO HIGH-ASSURANCE CLAIM**.

This tranche addresses issue #118. It defines what must be true about the
process, account, storage ACLs, and isolation boundary before ACP can make
stronger claims about the experimental repository mutation executor.

## Deployment classes

### LOCAL_TEST

Intended only for disposable/synthetic repository testing.

Minimum recorded evidence:

- absolute executable path;
- executable SHA-256;
- non-blank OS user identity;
- exact repository roots;
- authorization-store path;
- journal-store path;
- rollback-custody path;
- store paths distinct from repository roots and from each other.

A LOCAL_TEST pass means only that these identities and path separations are
represented coherently. It is not binary/process attestation.

### HIGH_ASSURANCE

HIGH_ASSURANCE fails closed unless all of the following are explicitly
established:

- dedicated service/worker OS identity;
- trusted launcher or executable identity;
- ACL separation between repository roots, authorization store, journal store,
  and rollback custody;
- OS isolation/sandbox boundary;
- peer-process tamper resistance for the stores and execution boundary.

The candidate assessment does not infer those controls from username, path,
administrator status, or an application-level executor ID.

## Preferred Windows deployment direction

For future higher-assurance evaluation, prefer a dedicated non-interactive
worker/service rather than an administrator's interactive desktop process.

Target architecture:

```text
operator / governance client
  -> authenticated narrow broker
  -> dedicated least-privilege ACP executor identity
       -> exact allowlisted disposable repository root
       -> authorization store ACL
       -> journal store ACL
       -> rollback custody ACL
       -> constrained process/job/sandbox boundary
```

The executor account should have only the filesystem rights required for the
explicit disposable target and its separately protected state stores. General
user-profile, desktop, DGAF, ACP source, Aetherwake, and unrelated project-tree
write access should not be inherited merely for convenience.

## Important non-equivalences

```text
EXECUTOR_ID_STRING != PROCESS_IDENTITY_ATTESTATION
EXECUTABLE_SHA256_RECORDED != TRUSTED_LAUNCHER
RUNNING_AS_ADMIN != LEAST_PRIVILEGE
DISTINCT_PATHS != ACL_SEPARATION
LOCAL_TEST_PASS != HIGH_ASSURANCE
```

## Current assessment ceiling

The current project has not established:

- a dedicated Windows service identity for the mutation executor;
- cryptographically trusted launcher/process attestation;
- verified ACL separation across repository/store/custody boundaries;
- AppContainer or equivalent sandbox;
- peer-process tamper resistance.

Therefore:

```text
LOCAL_TEST_PROCESS_BOUNDARY=ASSESSABLE
HIGH_ASSURANCE_PROCESS_BOUNDARY=NOT_ESTABLISHED
REAL_PROJECT_REPOSITORY_EXECUTION=NOT_AUTHORIZED
```

## Acceptance tests

The machine-checkable assessment must:

- admit LOCAL_TEST when identities are recorded and paths are separated;
- reject store paths aliasing a repository root;
- reject duplicate state-store paths;
- reject malformed executable hashes;
- reject HIGH_ASSURANCE when any required OS/process control is missing;
- admit the HIGH_ASSURANCE data model only when every required control is
  explicitly supplied.

A future implementation must verify those supplied controls from the operating
system or an independently trusted launcher; caller-provided booleans are only a
design-contract representation, not evidence that the controls truly exist.


## Reproducible Windows boundary audit

`scripts/inspect_executor_windows_boundary.ps1` now provides a read-only,
machine-readable audit of the local Windows boundary.

It records:

- current Windows user context and integrity level;
- executable path and SHA-256;
- repository ACL owner/SDDL/inheritance state;
- authorization-store ACL owner/SDDL/inheritance state;
- journal-store ACL owner/SDDL/inheritance state;
- rollback-custody ACL owner/SDDL/inheritance state;
- number of distinct ACL descriptors;
- whether ACL separation is observed;
- explicit false defaults for service identity, trusted launcher, OS isolation,
  and peer-process tamper resistance.

The script performs no account, ACL, service, executable, or security-policy
modification.

A local disposable-lab run on 2026-09-27 produced:

```text
READ_ONLY_AUDIT=true
DISTINCT_ACL_DESCRIPTOR_COUNT=1
ACL_SEPARATION_OBSERVED=false
DEDICATED_SERVICE_IDENTITY_VERIFIED=false
TRUSTED_LAUNCHER_IDENTITY_VERIFIED=false
OS_ISOLATION_VERIFIED=false
PEER_PROCESS_TAMPER_RESISTANCE_VERIFIED=false
HIGH_ASSURANCE_BOUNDARY_ESTABLISHED=false
```

Machine-specific user names, SIDs, owners, and SDDL are intentionally not
committed to the repository.

This converts the #118 boundary from a prose-only concern into a repeatable
operator audit while preserving the same assurance ceiling.


## Disposable executor-isolation lab harness — 2026-09-27

`scripts/setup_executor_isolation_lab.ps1` now provides a reversible, plan-first
fixture for the next #118 step.

Default behavior is non-privileged plan mode. It:

- creates only a disposable lab under `NDR-Ecosystem/staging`;
- defines separate repository, authorization, journal, and rollback paths;
- refuses a lab root inside DGAF, Aetherwake, or the ACP Active Projects tree;
- records whether the current process is elevated;
- records whether the dedicated `ACPExecutorLab` local identity already exists;
- emits the intended ACL/isolation controls without applying them.

The `-Apply` path fails closed unless the caller is elevated and the dedicated
worker identity was already created by an explicit elevated operator step. The
script deliberately does **not** create an account, generate/store a password,
install a service, or grant access to any real project tree.

Current RDC plan-mode evidence:

```text
current_process_is_administrator=false
worker_exists=false
apply_requested=false
real_project_roots_explicitly_excluded=true
```

This means the lab is operator-ready but privileged boundary establishment has
not occurred. The next privileged action must be explicit and separately
reviewable.

```text
DEDICATED_SERVICE_IDENTITY_VERIFIED=false
ACL_SEPARATION_OBSERVED=false
OS_ISOLATION_VERIFIED=false
PEER_PROCESS_TAMPER_RESISTANCE_VERIFIED=false
HIGH_ASSURANCE_BOUNDARY_ESTABLISHED=false
```


## Privileged disposable-lab read-back — 2026-09-27

An explicit elevated operator step created the local `ACPExecutorLab` identity and
applied the staged ACL fixture. Subsequent evidence collection was read-only.

Observed:
- worker exists and is enabled;
- worker is not a member of local Administrators;
- repository, authorization, journal, and rollback paths are four distinct
  disposable staging paths;
- all four paths have protected ACLs (inheritance disabled);
- all four paths grant the worker Modify/Synchronize and SYSTEM FullControl;
- no real DGAF, Aetherwake, or ACP Active Projects path was admitted by the setup
  harness.

The v0 audit incorrectly defined ACL separation as four distinct SDDL strings.
That would reject a valid design in which four distinct protected paths share the
same least-privilege descriptor. The v1 candidate instead verifies path
distinctness, ACL protection, worker SID grants on every path, and non-admin
worker status.

Read-back result:

```text
PATHS_DISTINCT=true
PROTECTED_ACL_PATH_COUNT=4
WORKER_ACL_PATH_COUNT=4
EXPECTED_WORKER_IS_ADMINISTRATOR=false
ACL_SEPARATION_OBSERVED=true
DEDICATED_SERVICE_IDENTITY_VERIFIED=false
TRUSTED_LAUNCHER_IDENTITY_VERIFIED=false
OS_ISOLATION_VERIFIED=false
PEER_PROCESS_TAMPER_RESISTANCE_VERIFIED=false
HIGH_ASSURANCE_BOUNDARY_ESTABLISHED=false
```

This establishes only the disposable lab's filesystem ACL isolation component.
It does not establish service/process identity or High-Assurance.


## Installed-service identity verification contract — 2026-09-27

A read-only installed-service identity verifier now exists before any real SCM
installation is attempted. It compares the observed SCM/CIM service record to an
exact expected service name, worker account, binary path, binary SHA-256, and
bounded start mode. Automatic start is outside the disposable-lab policy.

This deliberately separates **service installation** from **service identity
verification**. A successful install transaction alone cannot establish trusted
process identity.

Focused verifier + process-boundary + install-transaction/backend suite:
`34 passed, 1 skipped`.

No service was installed by this change.
