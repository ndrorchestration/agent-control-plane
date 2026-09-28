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


## Disposable SCM identity probe — 2026-09-27

No compiler or executable packager was already available on the host, so no new
packaging dependency was introduced merely to advance the gate. Instead, the
branch now contains an inert Python identity probe plus a deterministic launch
specification.

The probe:
- accepts only a path containing the disposable
  `staging/ACP-Executor-Isolation-Lab` boundary;
- has no executor/repository mutation capability;
- has a bounded hold interval (0..30 seconds);
- does not request auto-start or persistence.

The launch spec explicitly binds the Python executable, source root, module, and
lab root and uses Python isolated mode. It does not rely on ambient current
directory or PYTHONPATH. Local direct launch returned 0 with launch-spec SHA-256
`99ca6cea6d0b04cf05dbcb2c1bb80390f0c6349b15e2234a74bc485f7e975687`.

This is a launch-contract identity, not an immutable signed executable.
`TRUSTED_LAUNCHER_IDENTITY_VERIFIED` therefore remains false.


## Exact disposable SCM registration candidate — 2026-09-27

A non-mutating candidate builder now binds the proposed lab service registration
to the existing Python interpreter identity and the dedicated worker account.

Candidate:
- service: `ACPExecutorLabProbe`
- account: `.\ACPExecutorLab`
- start type: `DEMAND_START` (manual only)
- delayed auto-start: false
- credential reference: `operator-transient:ACPExecutorLab`
- manifest SHA-256: `dc216f2b490c86b948b30e8e206cdeede6f59b0cbdfa25105883fbc6c3f61b6b`
- interpreter SHA-256: `3adbbf2af609e206e3ca18cd55fc7c4b52f5c8bb8218dd99fd5a9e50d7a193cd`

The custom Windows account requires a secret. No plaintext password is stored in
the candidate, plan, source, documentation, Git history, or command line.
Credential resolution remains an explicit privileged operator action.

Focused registration/admission/install-transaction suite: `42 passed, 2 skipped`.

This candidate is still non-mutating. SCM registration has not occurred.


## Candidate correction — standalone SCM service probe

Pre-mutation review rejected the earlier interpreter-only candidate: its SCM
binary path would have named bare `python.exe`, while the inert Python probe
required arguments/source binding. Installing it would therefore have produced
misleading identity evidence.

The candidate was replaced before any SCM mutation. Windows includes the .NET
Framework C# compiler at
`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`, so a minimal
standalone `ServiceBase` probe was compiled without adding a third-party
packaging dependency.

Disposable artifact:
- `staging/ACP-Executor-Isolation-Lab/ACPExecutorLabProbe.exe`
- size: 4096 bytes
- SHA-256: `9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4`
- service name: `ACPExecutorLabProbe`
- account: `.\ACPExecutorLab`
- start type: demand/manual only
- manifest SHA-256: `3b1b8d9901263ad9ab814b454934b22b1b35bad42957d87224cfa148c54ad70c`

The source contains only Windows ServiceBase lifecycle handling; it has no ACP
executor import, repository path, mutation primitive, network behavior, or
auto-start request.

Revised candidate/admission suite: `28 passed, 2 skipped`.
SCM remains unmodified at this point.


## Operator-gated disposable SCM installation script

`scripts/install_disposable_scm_probe.ps1` is prepared but was not executed by
RDC. It requires an explicitly elevated interactive PowerShell and prompts for
the worker password as a SecureString. The password is not accepted as a
parameter and is not stored in source, Git, documentation, or command-line
arguments.

The script:
1. confines the binary to the disposable isolation-lab root;
2. re-verifies exact SHA-256 before SCM mutation;
3. requires Administrator context and an enabled worker;
4. refuses an existing service rather than overwriting it;
5. creates `ACPExecutorLabProbe` as Manual/Demand start only;
6. does not start the service;
7. reads CIM identity back immediately;
8. verifies service name, account, binary path/hash, manual start, and stopped state;
9. deletes the service if post-install identity verification fails.

Focused operator-script/candidate/identity/native-backend tests:
`20 passed, 1 skipped`.

The privileged installation remains a human-visible gate.


## SCM registration established — operator + independent read-back

The human-visible privileged registration step completed successfully.

Operator evidence:
- service `ACPExecutorLabProbe`;
- start account `.\ACPExecutorLab`;
- exact disposable probe path;
- start mode `Manual`;
- state `Stopped`;
- exact binary SHA-256
  `9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4`;
- all six post-install checks true.

Independent RDC read-back then observed the same service/account/path/start mode,
`State=Stopped`, `ProcessId=0`, and the same binary SHA-256. Focused
installed-identity/operator-script/candidate tests: `10 passed`.

This establishes **SCM registration identity for the stopped disposable
service**. It does not yet prove the process actually launches under that token,
nor trusted launcher/signature identity, OS isolation, or peer-process tamper
resistance. Service execution is therefore a separate next gate.


## Bounded running-process identity gate prepared

A separate read-only verifier now requires a running service with nonzero SCM
PID and checks:
- configured SCM account;
- process owner account;
- process owner SID against the local `ACPExecutorLab` SID;
- executable path;
- executable SHA-256.

The operator gate requires Administrator context, Manual start mode, and an
initial Stopped state. It starts the disposable service, invokes the read-only
identity verifier, and stops the service in a `finally` block. It then requires
the final SCM state to be Stopped.

Focused script contracts: `10 passed`.

No service start was performed by RDC while preparing this gate.


## First bounded start — blocked by missing service-logon right

The first operator start attempt failed before process creation. Independent
System-log inspection observed:
- SCM Event 7041: `.\ACPExecutorLab` was denied because it lacks
  `SeServiceLogonRight` ("Log on as a service");
- SCM Event 7000: resulting service start failure;
- service remained `Stopped`, PID 0.

This is an account-right admission blocker, not evidence of a probe-runtime
defect. `DEDICATED_SERVICE_PROCESS_IDENTITY_VERIFIED` remains false.

A minimal operator-gated script now grants only `SeServiceLogonRight` to the
exact local worker SID using Windows `secedit`, preserves existing principals
on that right, re-exports policy, and verifies the exact SID is present. It
does not add the worker to Administrators or grant other user rights.

Focused right-grant + process-gate contracts: `9 passed`.


## Service-logon grant verification correction

The first grant invocation reported `verified=false`, but Windows
`scesrv.log` independently records:
- exact worker SID `S-1-5-21-3119701800-1075537928-727562629-1005`;
- `add SeServiceLogonRight`;
- `User Rights configuration was completed successfully.`

The false negative was in script read-back: verification reused the original
export path and did not validate the second `secedit /export` exit code.
The corrected verifier exports to a fresh file, checks the exit code/file, and
normalizes both `*SID` and `SID` representations.

Focused correction + bounded-start contracts: `7 passed`.


## Effective service-logon right confirmed

Elevated diagnostic export succeeded with exit code 0 and returned:

`SeServiceLogonRight = ACPExecutorLab,*S-1-5-80-0,*S-1-5-99-0`

Therefore Windows retained the intended worker assignment but serialized the
local account as the exact name `ACPExecutorLab`, not its SID. Earlier
`verified=false` results were verifier false negatives caused by accepting
only SID serialization.

The grant/read-back verifier now accepts either the exact worker SID or exact
local account name, using equality rather than substring matching. No further
right mutation is required. Focused representation/grant/diagnostic/start-gate
contracts: `13 passed`.


## Second bounded start — filesystem access blocker

After the service-logon right was confirmed, a fresh bounded start failed again.
Independent SCM evidence changed to Event 7000 `Access is denied`; the prior
7041 logon-right event did not recur. Service remained Stopped with PID 0.

ACL inspection found the worker had no traversal/execution access through the
probe's location beneath `C:\Users\Admin`. Rather than widen access through
the operator profile, the next correction uses a dedicated machine-level
disposable directory:
`C:\ProgramData\NDR\ACP-Executor-Isolation-Lab`.

The operator-gated migration script:
- requires Administrator and exact ProgramData destination;
- requires the service be Stopped;
- verifies source and copied binary SHA-256;
- protects the destination ACL and grants only SYSTEM/Admin FullControl and
  exact worker ReadAndExecute;
- rebinds only the existing `ACPExecutorLabProbe` binary path;
- does not start the service or create another service;
- performs post-migration read-back checks.

Focused migration/process-gate contracts: `9 passed`.


## First successful live service process — verifier path stale

Post-ProgramData bounded execution successfully launched the inert service:
- SCM state Running;
- PID 10252;
- configured account `.\ACPExecutorLab`;
- observed process owner `NEONTIC\ACPExecutorLab`;
- observed owner SID exactly matched expected worker SID
  `S-1-5-21-3119701800-1075537928-727562629-1005`;
- observed process path
  `C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe`;
- observed SHA-256 exactly matched
  `9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4`;
- service returned to Stopped; independent RDC read-back observed PID 0.

Six of seven verifier checks were true. The sole false check,
`process_path_match`, was caused by the verifier retaining the pre-migration
profile-path default. The default is corrected to the ProgramData lab.
Focused verifier/start/migration contracts: `9 passed`.

Interpretation: live dedicated service process identity was directly observed,
but final machine-readable gate closure awaits one corrected-verifier rerun.


## Dedicated live service process identity — VERIFIED

Corrected bounded run produced a complete machine-readable PASS:
- service state Running during observation;
- PID 5404;
- SCM account `.\ACPExecutorLab`;
- process owner `NEONTIC\ACPExecutorLab`;
- process owner SID exactly
  `S-1-5-21-3119701800-1075537928-727562629-1005`;
- process path exactly
  `C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\ACPExecutorLabProbe.exe`;
- process SHA-256 exactly
  `9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4`;
- all seven verifier checks true;
- `verified=true`;
- bounded start/stop completed true.

Independent RDC read-back after the run observed `State=Stopped`,
`ProcessId=0`, Manual start mode, the exact ProgramData binary path, and the
same configured worker account.

Scoped conclusion:
`DEDICATED_SERVICE_PROCESS_IDENTITY_VERIFIED=true` for this disposable lab
probe.

Not established by this result:
`TRUSTED_LAUNCHER_IDENTITY_VERIFIED=false`
`OS_ISOLATION_VERIFIED=false`
`PEER_PROCESS_TAMPER_RESISTANCE_VERIFIED=false`
`HIGH_ASSURANCE_BOUNDARY_ESTABLISHED=false`
`REAL_PROJECT_REPOSITORY_EXECUTION=NOT_AUTHORIZED`.


## OS isolation frontier — restricted service SID candidate

Read-only baseline after dedicated process identity verification:
- `sc qsidtype ACPExecutorLabProbe` => `SERVICE_SID_TYPE: NONE`;
- `sc qprivs ACPExecutorLabProbe` => no configured required-privilege list.

The next bounded isolation transition is a restricted service SID on the
disposable probe only. The operator-gated script requires Administrator,
exact service name, Stopped state, Manual start mode, and the dedicated worker
account before invoking `sc sidtype ACPExecutorLabProbe restricted`. It does
not start the service, create a service, change its account/path, or touch a
real repository. A separate read-only verifier queries the resulting SID type.

Focused contracts: `7 passed`.

This candidate alone does not establish OS isolation. Required evidence is:
restricted SID read-back, then a bounded live identity rerun showing the
service still executes as the verified worker and returns to Stopped. Further
tamper/ACL isolation tests remain separate.


## Restricted service SID — configuration VERIFIED

Operator-gated transition returned:
`service_sid_type=RESTRICTED`, `verified=true`.
Separate read-only verifier returned:
`service_sid_type=RESTRICTED`, `restricted=true`.

Independent RDC read-back also observed
`SERVICE_SID_TYPE: RESTRICTED`, with the service Stopped, PID 0, Manual start,
the dedicated `.\ACPExecutorLab` account, and exact ProgramData probe path.

Scoped state:
`RESTRICTED_SERVICE_SID_CONFIGURED=true`.

This is configuration evidence, not yet live compatibility evidence. One
bounded start/identity/stop cycle under the restricted SID remains required
before treating this containment control as operational. Even a successful
cycle will not by itself establish complete OS isolation or peer-process
tamper resistance.


## Restricted service SID — live compatibility VERIFIED

A bounded post-transition live run produced a complete PASS while
`SERVICE_SID_TYPE=RESTRICTED`:
- PID 16880;
- SCM account `.\ACPExecutorLab`;
- process owner `NEONTIC\ACPExecutorLab`;
- exact worker SID `S-1-5-21-3119701800-1075537928-727562629-1005`;
- exact ProgramData probe path;
- exact SHA-256 `9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4`;
- all seven process identity checks true;
- `verified=true`;
- bounded start/stop completed true.

Independent RDC read-back after the run observed:
`SERVICE_SID_TYPE=RESTRICTED`, service Stopped, PID 0, Manual start, exact
worker account, and exact ProgramData path.

Scoped conclusion:
`RESTRICTED_SERVICE_SID_OPERATIONAL=true` for the disposable lab service.
This establishes one concrete OS containment control, but not complete
`OS_ISOLATION_VERIFIED` or peer-process tamper resistance. Trusted launcher
identity, broader token/privilege confinement, and real-repository execution
remain separately gated.


## OS isolation evidence model — containment vs minimal token

Read-only characterization after restricted-SID compatibility:
- service is `WIN32_OWN_PROCESS`, demand/manual start;
- dedicated non-admin account remains `.\ACPExecutorLab`;
- `SERVICE_SID_TYPE=RESTRICTED`;
- no explicit required-privilege list is configured;
- no worker ACL entry is present on the real NDR-Ecosystem, DGAF & Governance,
  or Aetherwake roots;
- the protected ProgramData lab is not ACL-readable by the ordinary RDC
  process, consistent with its narrow boundary.

A fail-closed evidence model now distinguishes:
1. concrete containment controls already established;
2. explicit required-privilege configuration;
3. live effective-token observation;
4. complete OS-isolation claims.

The model deliberately cannot promote complete OS isolation. Current evidence
supports containment controls, but `MINIMAL_SERVICE_TOKEN_VERIFIED=false`
because no required-privilege allowlist or live token privilege observation
has been established.


## Minimal-token frontier — observer boundary

A new read-only token characterization contract records an important evidence
boundary: `whoami /priv` invoked by an external PowerShell verifier describes
the verifier's token, not the service process token. It therefore cannot be
used as live service-token evidence.

The characterization script may read the SCM configured required-privilege
list, but deliberately emits:
`live_service_token_privileges_observed=false`,
`observer_privileges_not_service_evidence=true`, and
`minimal_service_token_verified=false`.

This prevents a false promotion from configuration metadata or observer-token
output. Real effective-token evidence requires either a trustworthy
process-token inspection primitive or a narrowly scoped disposable service
self-report whose identity/hash remains bound to the established probe.


## Self-reporting service-token probe — operator-ready

A separate disposable service binary now self-reports only its own effective
token privilege inventory to:
`C:\ProgramData\NDR\ACP-Executor-Isolation-Lab\token-evidence.json`.

Source is in-repo as `scripts/ACPExecutorTokenProbe.cs`. It has no network
or repository access and retains the same SCM service name/stop behavior.
Current build SHA-256:
`642ca4a7a9569a04ce5512c53ffe004eee7c2ce0b8759872778474607dd8d4b0`.

A read-only evidence parser verifies schema/PID and emits
`live_service_token_privileges_observed=true` while deliberately retaining
`minimal_service_token_verified=false` until policy/adjudication.

A reversible operator-gated rebind script:
- requires Administrator;
- exact disposable service only;
- requires Stopped, Manual, dedicated ACPExecutorLab account, RESTRICTED service SID;
- verifies old inert-probe SHA-256 `9215cd763d325abf43c4fcb1a2b4b222aa7ce9c27059103107bbea749974eab4`;
- verifies new token-probe SHA-256 `642ca4a7a9569a04ce5512c53ffe004eee7c2ce0b8759872778474607dd8d4b0`;
- preserves a hash-verified backup of the old probe;
- copies only the new binary into the already isolated ProgramData path;
- restores the backup if installed-hash verification fails;
- does not start the service or alter account/start/SID configuration.

Focused rebind/parser/source contracts: `10 passed`.
