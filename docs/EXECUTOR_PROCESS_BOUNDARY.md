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
