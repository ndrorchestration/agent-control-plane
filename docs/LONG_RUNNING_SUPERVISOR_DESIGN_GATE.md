# Long-Running Supervisor Design Gate

Status: **DESIGN PREREQUISITES SATISFIED — UNBOUNDED DAEMON IMPLEMENTATION NOT YET ESTABLISHED**

This gate separates accepted bounded supervision primitives from any future continuously running ACP supervisor.

## Already accepted beneath this gate

- durable relay queues, retry/backoff, dead-letter state and local capacity limits;
- deterministic relay supervisor cycles;
- process restart/hold/give-up policy;
- real bounded subprocess start/observe/terminate/restart;
- durable one-shot crash monitoring;
- persisted monitoring cadence;
- finite scheduled monitor runner.

These do **not** establish a service or daemon.

## Service lifecycle contract

A future long-running supervisor must obey the typed lifecycle:

`CREATED -> STARTING -> RUNNING -> STOP_REQUESTED -> STOPPING -> STOPPED`

Failure may terminate non-terminal states as:

`* -> FAILED`

Terminal states must not silently transition back to running.

Supported initial stop sources:

- explicit operator request;
- SIGTERM;
- SIGINT;
- worker give-up;
- startup failure;
- internal error.

Unsupported signals fail closed until assigned explicit semantics.

## Worker ownership invariants

Each managed worker requires unique:

- `worker_id`;
- `process_id`;
- `ownership_token`.

One supervisor instance must not claim two workers with the same process identity or ownership token.

A future persistent ownership lease must define:

- acquisition;
- renewal;
- expiry;
- takeover rules;
- stale-owner recovery;
- split-brain prevention.

None are established by this design slice.

## Graceful shutdown requirements

Before an unbounded runtime is admissible, implementation must prove:

1. stop request is latched once accepted;
2. no new worker restart is initiated after stop request;
3. pending monitor/retry cycle either completes or is explicitly cancelled;
4. each managed child receives bounded graceful termination;
5. kill fallback is bounded and evidenced;
6. durable queues/failure state are left in a recoverable form;
7. service exits with an explicit terminal reason;
8. repeated SIGTERM/SIGINT cannot create duplicate teardown;
9. shutdown cannot reactivate a stopped worker.

## Multi-worker scheduling requirements

A future supervisor managing more than one worker must define:

- deterministic worker ordering or fair scheduling;
- per-worker failure/restart state;
- concurrency bound;
- isolation of one worker crash from unrelated workers;
- global stop behavior;
- whether one worker `give_up` blocks the whole service or only that worker;
- queue/retry resource limits across workers.

No multi-worker concurrent runtime is established yet.

## Persistence requirements

A future long-running runtime must persist enough state to distinguish:

- clean shutdown;
- crash;
- restart in progress;
- terminal give-up;
- stale ownership from a previous supervisor process.

Persistence writes must have explicit ordering relative to worker restart/termination actions.

## Security requirements before service installation

An installable supervisor must not accept arbitrary executables by default.

Required design work includes:

- executable allow-list or immutable worker specs;
- environment-variable policy;
- working-directory policy;
- inherited descriptor policy;
- privilege/user boundary;
- secret/key access boundary;
- log redaction;
- filesystem permissions for SQLite state;
- service account strategy.

## OS/service-manager boundary

Systemd, Windows Service Control Manager, launchd, containers, Kubernetes, or any other service manager remain separate adapters.

A platform adapter must not redefine ACP lifecycle semantics. It may translate external service events into the typed service contract.

## Acceptance gates before unbounded daemon work

At minimum:

- [x] lifecycle state machine tests PASS — #57;
- [x] SIGTERM graceful-shutdown test PASS — #59;
- [x] SIGINT graceful-shutdown test PASS — #59;
- [x] repeated-signal idempotence test PASS — #58 / #59;
- [x] child crash during shutdown test PASS — #67;
- [x] multi-worker ownership-conflict tests PASS — #57 / #60 / #61;
- [x] restart forbidden after stop-request test PASS — #58 / #67;
- [x] persistent ownership/restart state defined and tested — #60–#65;
- [x] bounded concurrency semantics defined — #69 (`max_in_flight_workers=1`, contract-order serial);
- [x] executable/privilege policy defined — #68 (pre-spawn executable/CWD/environment/spec/UID admission; no sandbox claim);
- [x] finite integration test proves startup -> run -> signal -> clean stop — #59;
- [x] exact evidence boundary documented — #57–#69.

These prerequisite gates are now satisfied for the bounded local evidence model.

**LONG_RUNNING_SUPERVISOR_IMPLEMENTATION = ADMISSIBLE_AS_EXPERIMENTAL_CANDIDATE**

This does **not** mean a daemon is established, production-ready, or authorized for unattended deployment. Any unbounded implementation must still pass its own exact-head integration evidence, preserve the accepted lifecycle/ownership/recovery/admission boundaries, and remain fail-closed on unsupported platform/service-manager behavior.


## Bounded service-runner candidate

A finite multi-worker service runner now exists as a candidate integration step beneath this gate.

It composes:
- the typed supervisor lifecycle contract;
- explicit worker ownership registrations;
- accepted managed-process controllers;
- accepted scheduled process monitors;
- an explicit maximum cycle count;
- injected signal input;
- bounded reverse-order worker termination.

Candidate invariants:
- SIGTERM/SIGINT are checked before each cycle;
- once stop is requested, no new monitor cycle starts;
- repeated stop signals preserve the first latched reason;
- finite completion maps to an explicit operator-requested stop;
- all configured child processes are terminated before the service reaches `STOPPED`;
- runtime worker order must exactly match contract worker order.

This remains finite and caller-started. It is not an unbounded daemon.


## Real OS-signal integration candidate

A dedicated Linux integration candidate now launches the finite bounded supervisor in a child process and sends real OS signals from a parent harness.

Required evidence for both SIGTERM and SIGINT:
- supervisor process reaches ready state;
- parent delivers the actual OS signal;
- typed service lifecycle records the corresponding first stop reason;
- bounded shutdown completes;
- managed worker is no longer running;
- supervisor exits normally in terminal `STOPPED` state.

This closes only the OS-signal translation and finite graceful-shutdown proof. It does not establish an unbounded daemon, service registration, reboot persistence, signal behavior on Windows Service Control Manager, or production watchdog availability.


## Durable supervisor ownership lease candidate

ACP now has a SQLite-backed ownership lease primitive for worker/service resources.

Each lease binds:
- resource ID;
- logical owner ID;
- per-instance ownership token;
- monotonic fencing token;
- acquired / renewed / expiry timestamps;
- optional release timestamp.

Acquisition occurs under a SQLite write lock. A competing owner is rejected while the lease is active. An expired or explicitly released lease may be taken over, but every takeover increments the fencing token.

Renew and release operations must match the current owner ID, ownership token and fencing token. A stale supervisor instance therefore cannot renew or release a lease after takeover. Expired leases cannot be renewed; they must be reacquired and receive a new fencing token.

This closes only the local durable ownership/fencing primitive. The bounded supervisor runner does not yet require a lease before worker control, and no cross-host distributed lease/consensus claim is established.


## Lease-enforced bounded supervisor runner candidate

The bounded multi-worker supervisor can now optionally enforce the durable fenced ownership lease primitive.

When lease enforcement is configured:

1. every worker resource lease is acquired before any child process starts;
2. competing active ownership fails startup closed;
3. each lease is asserted current and renewed before any new monitor-cycle work;
4. a stale, expired, or taken-over fence requests service stop before another worker monitor executes;
5. workers are terminated before lease release;
6. stale lease release failure is treated as an internal service failure rather than silently clearing another owner's lease;
7. the report records the fencing token used for each worker resource.

This materially narrows local split-brain risk for the tested SQLite-backed single-host model. It does not establish distributed consensus, cross-host clock correctness, partition-safe leases, or fencing enforcement by external resources themselves.


## Durable supervisor runtime checkpoint candidate

ACP now has a generation-fenced SQLite runtime checkpoint for supervisor-service state.

Each service checkpoint binds:
- service ID;
- monotonically increasing runtime generation;
- owner ID;
- ownership fencing token;
- lifecycle state;
- optional stop reason;
- update timestamp.

A new run atomically replaces the previous generation with `STARTING` and returns a recovery assessment of the previous state:

- `fresh` — no prior checkpoint;
- `clean_stop` — prior generation reached `STOPPED`;
- `unclean_exit` — prior generation ended in a nonterminal state;
- `terminal_give_up` — prior generation failed due to worker give-up;
- `prior_failure` — prior generation ended in another failure.

The assessment separately marks whether the prior owner/fence differs from the new owner/fence.

Checkpoint updates are generation- and fence-bound. Once a newer run begins, an older supervisor instance cannot overwrite the persisted lifecycle state.

This closes durable recovery classification only. The bounded supervisor runner does not yet write its lifecycle transitions into this store, and no automatic recovery decision is inferred from the classification.


## Checkpoint-enforced bounded supervisor runner candidate

The bounded supervisor can now combine service-level fenced ownership with the durable runtime checkpoint.

When runtime checkpointing is configured:

1. a dedicated service ownership lease is acquired before worker leases/process start;
2. `begin_run` persists a new generation in `STARTING` bound to that service fence;
3. successful child startup persists `RUNNING`;
4. signal/operator/worker-give-up/internal stop requests persist `STOP_REQUESTED`;
5. `STOPPING` is persisted before child termination;
6. children terminate before lease release;
7. lease release occurs before a clean terminal `STOPPED` checkpoint;
8. terminal `STOPPED` is persisted before the in-memory contract claims clean stop;
9. startup failure persists `FAILED / startup_failure` and releases acquired leases;
10. a newer runtime generation prevents stale-generation lifecycle writes.

The runner report exposes the service fencing token, runtime generation and previous-run recovery assessment separately from worker fencing tokens.

This closes bounded local lifecycle persistence ordering and recovery classification. It does not authorize automatic recovery action from an unclean prior generation, unbounded daemon operation, distributed ownership, or service-manager reboot recovery.


## Fail-closed recovery admission candidate

The checkpoint-enforced supervisor now has an explicit startup admission policy over the previous runtime generation.

Default admission:

- `fresh` -> ALLOW;
- `clean_stop` -> ALLOW;
- `unclean_exit` -> HOLD;
- `terminal_give_up` -> HOLD;
- `prior_failure` -> HOLD.

A HOLD occurs after the prospective service/worker leases are acquired but **before any new runtime generation or worker process starts**. The exact prior checkpoint remains intact, all newly acquired leases are released, and the report retains both the prior recovery assessment and the in-memory `FAILED / recovery_hold` outcome. This avoids shadowing the checkpoint that an operator may need to authorize.

A caller may explicitly widen the allowed disposition set. There is no implicit automatic recovery from unclean or failed prior state.

This establishes local fail-closed recovery admission only. It does not establish remediation of the prior failure, operator authorization UX, distributed recovery, or service-manager restart policy.


## Exact one-time recovery authorization candidate

A held non-clean recovery may now be authorized only by an exact durable record.

`SupervisorRecoveryAuthorizationStore` binds one authorization ID to:

- service ID;
- exact previous runtime generation;
- previous owner ID;
- previous ownership fencing token;
- SHA-256 of the complete prior checkpoint;
- exact previous-run disposition;
- operator label (`authorized_by`);
- issue time;
- expiry time;
- single-use consumption time.

The runner assesses recovery **before** creating the next runtime generation. If the default recovery policy returns HOLD, an optional configured authorization is consumed against that exact assessment. Only a successful exact match changes the startup decision to ALLOW; then and only then is the next runtime generation created.

Fail-closed cases include:

- wrong or changed prior generation;
- wrong prior fence/owner/checkpoint hash;
- wrong disposition;
- expired authorization;
- missing authorization;
- already consumed authorization;
- terminal give-up unless `allow_terminal_give_up=true` is separately configured.

A HOLD with no valid authorization does not mutate the prior runtime checkpoint and starts no worker.

The `authorized_by` field is an audit label supplied by the caller; this slice does not authenticate a human operator, implement RBAC/MFA, provide an approval UI, or establish cryptographic operator signatures.


## Shutdown race / kill-fallback evidence candidate

A focused shutdown-invariants candidate adds direct evidence for two remaining graceful-shutdown requirements.

### Stop-request restart suppression

The test uses a worker that exits independently between monitor cycles. The next cycle receives a stop request **before** any monitor work. Acceptance requires:

- the service records the stop reason;
- no crash monitor runs against the exited worker;
- no restart is attempted;
- the durable failure counter remains unchanged;
- shutdown completes in `STOPPED`;
- the original worker exit code is preserved.

### Bounded kill fallback

A real child process deliberately ignores `SIGTERM`. Acceptance requires the managed-process controller to wait only for the configured timeout, then use its kill fallback and return a terminal non-running observation.

Until exact-head CI is green, these remain candidate evidence.


## Process execution admission candidate

A fail-closed launch-admission layer now exists as a candidate security gate before service installation.

`ProcessExecutionAdmissionPolicy` can require:

- exact admitted executable paths;
- working directories under configured roots;
- explicit environment mappings instead of unrestricted inherited environment;
- admitted environment-variable names;
- explicit forbidden environment-variable names;
- SHA-256 binding to an immutable `ManagedProcessSpec` representation;
- an expected effective UID when the platform exposes one.

`AdmittedManagedProcessController` performs the admission check immediately before calling the accepted subprocess start primitive. A denied launch produces no child PID.

The spec fingerprint covers process ID, complete argv, canonical working directory, and sorted explicit environment mapping.

This is **not** a sandbox. It does not:
- change UID/GID;
- create namespaces, containers, chroots or seccomp profiles;
- secure secrets in memory;
- prevent an admitted executable from opening arbitrary files or sockets;
- define Windows service-account semantics;
- establish code signing or package provenance.

Until exact-head CI passes, this remains candidate evidence toward the executable/privilege-policy gate.


## Explicit serial concurrency candidate

The current bounded supervisor scheduling model is now represented by an explicit `SupervisorConcurrencyPolicy`.

Candidate semantics:

- scheduling mode is `contract_order_serial`;
- worker monitor actions follow the service contract's worker order;
- `max_in_flight_workers = 1`;
- the runner reports the active scheduling mode and concurrency limit;
- any request for parallelism greater than one fails closed.

This satisfies bounded-concurrency semantics by making the current single-in-flight model explicit rather than implying unsupported parallel execution. It does **not** establish concurrent worker monitoring, thread/process pools, fairness under parallel scheduling, or parallel failure isolation.

Until exact-head CI passes, this remains candidate evidence.


## 2026-09-26 gate reconciliation

Accepted protected main after #69: `6757f6c06465fa899b2620a76eea3259362e6483`.

The original prerequisite list is now fully evidenced under the current bounded local model.

Notably:
- #59 established real finite SIGTERM/SIGINT handling;
- #60–#61 established durable local ownership leases and runner fencing;
- #62–#65 established persisted runtime generations, fail-closed recovery admission, and exact one-time recovery authorization;
- #67 closed shutdown-race restart suppression and bounded kill-fallback evidence;
- #68 added fail-closed pre-spawn process execution admission;
- #69 made the current concurrency model explicit: contract-order serial with one in-flight worker action.

The next valid engineering step is an **experimental unbounded supervisor runtime candidate**. It must reuse—not bypass—the accepted lifecycle contract, ownership fences, checkpoint/recovery policy, execution admission, signal handling, and serial concurrency contract.

Still outside the evidence boundary:
- systemd / Windows SCM / launchd installation;
- reboot persistence;
- cross-host lease correctness or consensus;
- Windows service-account semantics;
- privilege dropping or sandbox isolation;
- production watchdog/SLA claims;
- unattended production authorization.


## Experimental unbounded-cycle supervisor candidate

The prerequisite gate is now satisfied, so ACP has an experimental candidate that removes only the finite cycle ceiling from the accepted supervisor runner core.

`ExperimentalLongRunningSupervisorServiceRunner` reuses the same implementation for:

- typed service lifecycle;
- worker/service fenced ownership leases;
- generation-fenced runtime checkpoints;
- fail-closed recovery admission and exact one-time recovery authorization;
- process execution admission supplied by worker controllers;
- real SIGTERM/SIGINT signal translation;
- serial contract-order concurrency with one in-flight worker monitor action;
- bounded child termination and kill fallback.

The bounded runner still rejects `max_cycles=None`. Unbounded cycles require the separately named experimental runner.

### Dedicated integration gate

The `experimental-long-running-supervisor` CI workflow launches the experimental runner as a real process with:

- an admitted worker executable/spec/environment/CWD;
- service and worker ownership leases;
- durable runtime checkpointing;
- real OS signal registration.

For both SIGTERM and SIGINT the parent harness requires:

- supervisor reaches the running cycle;
- actual OS signal is delivered;
- final service lifecycle is `STOPPED`;
- typed stop reason matches the signal;
- child worker is stopped;
- durable runtime checkpoint reaches `STOPPED`;
- runtime generation is recorded;
- service ownership lease is released.

Accepted exact-head evidence on protected main `a7f98d5aadbae12cc745f5d70b13d892aed4746e` establishes:

**EXPERIMENTAL_LONG_RUNNING_SUPERVISOR = ESTABLISHED_BOUNDED_LOCAL_LINUX**

Even after a green merge this remains experimental local Linux evidence. It does not establish service installation, reboot persistence, Windows SCM/launchd/systemd semantics, distributed ownership, privilege dropping, production watchdog availability, or unattended production authorization.


## 2026-09-26 experimental long-running establishment

PR #71 merged as protected main `a7f98d5aadbae12cc745f5d70b13d892aed4746e`.

Exact-head evidence:
- Python 3.10–3.14 PASS;
- existing finite OS-signal supervisor regression PASS;
- dedicated experimental long-running supervisor gate PASS;
- real SIGTERM case PASS;
- real SIGINT case PASS;
- final lifecycle `STOPPED`;
- signal-specific stop reason preserved;
- managed child stopped;
- durable runtime checkpoint reached `STOPPED`;
- runtime generation recorded;
- service ownership lease released.

This establishes the experimental unbounded-cycle supervisor only within the tested local Linux model. Platform service installation, reboot persistence, distributed ownership, privilege dropping/sandboxing, and production unattended operation remain outside the evidence boundary.


## Platform-neutral service-host event candidate

ACP now has a candidate adapter boundary for service managers that do not communicate through POSIX signals.

`SupervisorServiceHostEventLatch` latches the first supported external host event and maps it to a typed ACP stop reason:

- `stop` -> `service_stop`;
- `shutdown` -> `service_shutdown`.

The supervisor runner consumes these typed stop reasons through a dedicated provider that is separate from the existing SIGTERM/SIGINT provider. Unsupported or non-enum host events fail closed.

This preserves the OS/service-manager boundary: systemd, Windows SCM, launchd, containers, and other hosts may translate their native events into this contract, but they may not redefine ACP lifecycle, ownership, recovery, or process-control semantics.

This slice does not yet implement any concrete systemd, Windows SCM, or launchd service registration.


## Windows SCM control translation candidate

ACP now has a pure translation candidate for Windows Service Control Manager control codes.

The adapter preserves ACP lifecycle semantics rather than redefining them:

- `SERVICE_CONTROL_STOP (0x00000001)` -> host `stop` -> ACP `service_stop`;
- `SERVICE_CONTROL_SHUTDOWN (0x00000005)` -> host `shutdown` -> ACP `service_shutdown`;
- `SERVICE_CONTROL_PRESHUTDOWN (0x0000000F)` -> host `preshutdown` -> ACP `service_preshutdown`;
- `SERVICE_CONTROL_INTERROGATE (0x00000004)` -> status-only, no stop event.

Pause/continue controls fail closed because ACP has no accepted pause/resume lifecycle state.

The runner composition tests prove STOP and PRESHUTDOWN reach the existing typed lifecycle and terminate managed workers cleanly.

This remains a pure adapter layer. No Windows service is installed or registered, no `ServiceMain`/HandlerEx callback is hosted, and Windows service-account/reboot semantics remain unestablished.


## Windows SCM ServiceMain / HandlerEx host-contract candidate

ACP now has a pure Windows-service host contract above the accepted SCM control translator.

`WindowsScmServiceHostContract` models the callback-facing state that a future native ServiceMain/HandlerEx adapter must report:

- `STOPPED`;
- `START_PENDING`;
- `RUNNING`;
- `STOP_PENDING`;
- terminal `STOPPED`.

It also models:

- accepted control flags for STOP / SHUTDOWN / PRESHUTDOWN only while running;
- checkpoint and wait-hint values for pending states;
- status-only INTERROGATE handling;
- first-stop-event latching;
- Win32 and service-specific terminal exit codes;
- a `stop_reason_provider` compatible with the existing ACP supervisor runner.

Composition tests prove an SCM STOP arriving between bounded supervisor cycles is translated into the existing typed `service_stop` lifecycle reason before further monitor work, and managed workers shut down through the existing supervisor path.

This remains a pure host contract. It does **not**:
- call StartServiceCtrlDispatcher;
- register a ServiceMain callback;
- register HandlerEx with Windows SCM;
- install/create/delete a Windows service;
- configure recovery actions;
- establish reboot persistence;
- define service-account/ACL behavior;
- prove behavior on a real Windows SCM host.

Until exact-head CI passes, this remains candidate evidence.


## Native Windows SCM ABI candidate

ACP now has a dependency-free `ctypes` binding candidate for the minimal native service-host APIs required by a future Windows service entrypoint.

The candidate validates and binds:

- `StartServiceCtrlDispatcherW`;
- `RegisterServiceCtrlHandlerExW`;
- `SetServiceStatus`.

It also maps the accepted `WindowsScmServiceStatus` into the native `SERVICE_STATUS` structure, preserving:

- service type;
- current state;
- accepted control mask;
- Win32 exit code;
- service-specific exit code;
- checkpoint;
- wait hint.

The module fails closed off Windows when native bindings are requested.

### Evidence gates

- ordinary Python CI checks cross-platform import/mapping/fail-closed behavior;
- dedicated `windows-scm-native-probe` CI runs on `windows-latest` and requires the actual Advapi32 exports and Windows callback ABI;
- operator-local corroboration on a non-elevated Windows 11 build 26200 / Python 3.14.5 environment produced `5 passed, 1 skipped` for the native test file.

This still does **not** call the dispatcher, register callbacks with SCM, create/install a service, mutate SCM configuration, require elevation, establish reboot persistence, or prove service-account behavior.


## Native Windows SCM callback-runtime candidate

ACP now has a candidate runtime that composes the accepted Windows SCM host contract with the dependency-free native bindings.

The runtime:

- creates native ServiceMain and HandlerEx callback objects;
- registers HandlerEx through `RegisterServiceCtrlHandlerExW`;
- publishes `START_PENDING` immediately after handler registration;
- publishes `RUNNING` before service work begins;
- translates native controls through the accepted `WindowsScmServiceHostContract`;
- republishes status for INTERROGATE;
- publishes `STOP_PENDING` for accepted stop/shutdown/preshutdown controls;
- returns `ERROR_CALL_NOT_IMPLEMENTED` for controls ACP does not admit;
- contains Python exceptions at the native callback boundary;
- publishes terminal `STOPPED`, using service-specific error reporting when the service callable fails;
- can invoke `StartServiceCtrlDispatcherW` through the accepted native binding wrapper.

### Evidence boundary

Cross-platform tests use an injected fake native backend to verify exact callback/status sequencing without pretending to be SCM.

The Windows-specific gate validates the callback ABI and native exports on `windows-latest`.

Operator-local corroboration on the connected Windows 11 build 26200 / Python 3.14.5 machine produced `11 passed, 1 expected skip` for the native binding + callback-runtime test set.

This still does **not**:
- install/create/delete a Windows service;
- prove ServiceMain execution under an actual SCM-launched service process;
- configure SCM recovery actions;
- establish reboot persistence;
- define service-account/ACL behavior;
- authorize production Windows-service operation.


## Windows SCM dispatcher fail-closed candidate

The native dispatcher wrapper is now explicitly tested from a normal Windows console process.

Expected behavior:

- `StartServiceCtrlDispatcherW` must fail when the process was not launched by SCM;
- ACP surfaces Windows error `1063` (`ERROR_FAILED_SERVICE_CONTROLLER_CONNECT`);
- ServiceMain logic must therefore not run merely because a user starts the executable interactively.

Operator-local corroboration on Windows 11 build 26200 produced `ERRNO=1063`.

The dedicated Windows CI gate must reproduce the same condition before this evidence is accepted.

This proves only the negative console-launch boundary. It does not prove successful SCM-launched dispatch, service installation, reboot persistence, or service-account behavior.


## Windows service registration manifest candidate

ACP now has a fail-closed, non-mutating Windows service registration manifest and admission policy.

`WindowsScmServiceRegistrationManifest` records:

- service name and display name;
- canonical absolute Windows binary path;
- explicit service account;
- start type;
- description;
- dependency set;
- delayed-auto-start intent;
- opaque credential reference instead of plaintext credentials;
- optional binary SHA-256;
- canonical manifest SHA-256 identity.

`WindowsScmServiceRegistrationPolicy` can require:

- exact admitted binary paths;
- exact admitted service accounts;
- admitted start types;
- optional exact manifest hashes;
- explicit LocalSystem permission;
- explicit delayed-auto-start permission;
- presence of a binary SHA-256.

Default policy accepts demand-start only. LocalSystem and auto-start are fail-closed unless explicitly admitted.

This is intent admission only. The supplied `binary_sha256` is an identity claim in the manifest; this slice does not read or independently hash the binary on disk.

Operator-local corroboration on the connected Windows 11 build 26200 / Python 3.14.5 environment produced `14 passed` for the registration-manifest test set.

This still does **not**:
- call CreateServiceW or ChangeServiceConfig2W;
- create, modify, start, stop, or delete any Windows service;
- store or retrieve actual credentials;
- establish service-account ACLs;
- enable reboot persistence;
- configure failure/recovery actions;
- authorize production installation.


## On-disk Windows service binary verification candidate

ACP now has a candidate verifier for the registration manifest's declared service binary identity.

`WindowsScmBinaryVerifier`:

- requires Windows for real file verification;
- requires the manifest to carry `binary_sha256`;
- requires the path to exist and be a regular file;
- hashes the actual file bytes with SHA-256;
- records actual size and modification timestamp;
- compares pre/post file metadata to detect a file changing during verification;
- fails closed on missing files, non-files, concurrent change, size inconsistency, or digest mismatch.

`WindowsScmServiceRegistrationAdmission` composes:
1. the accepted registration-intent policy;
2. exact manifest identity;
3. actual on-disk binary verification.

Operator-local Windows corroboration on the connected Windows 11 build 26200 / Python 3.14.5 machine produced `6 passed, 1 expected skip` for the binary-verification test file.

This is still not code signing, Authenticode verification, publisher identity, protected deployment, anti-tamper storage, or an SCM mutation. A file that matches the configured SHA-256 is byte-identical to the admitted artifact; no broader trust claim is implied.


## Non-mutating Windows service registration call-plan candidate

ACP now has a dry-run compiler for the privileged SCM registration boundary.

`WindowsScmServiceRegistrationPlanner` first applies the existing fail-closed manifest policy, then compiles admitted intent into exact call data for a future native registration adapter:

- service and display names;
- quoted binary command path;
- `SERVICE_WIN32_OWN_PROCESS`;
- exact SCM start type;
- normal error control;
- dependency MULTI_SZ encoding;
- service account;
- opaque credential reference only;
- whether credential resolution is required;
- delayed-auto-start intent;
- exact desired SCM access mask;
- exact desired service access mask.

Credential behavior is explicit:

- LocalSystem/LocalService/NetworkService and `NT SERVICE\...` virtual accounts do not require a secret;
- other admitted accounts require an opaque `credential_reference`;
- no plaintext password field exists in the plan.

A Windows-native capability probe verifies availability of:

- `OpenSCManagerW`;
- `CreateServiceW`;
- `ChangeServiceConfig2W`;
- `CloseServiceHandle`.

Operator-local Windows corroboration on the connected Windows 11 build 26200 / Python 3.14.5 machine produced `6 passed, 1 expected skip`, and all four required registration exports were present.

This slice remains non-mutating. It does not open SCM handles, create a service, resolve credentials, configure recovery actions, start a service, or establish reboot persistence.


## Exact Windows service installation authorization candidate

Before any privileged SCM mutation is added, ACP now has a candidate exact authorization layer.

`WindowsScmInstallationTarget` binds:

- service name;
- admitted registration-manifest SHA-256;
- verified actual binary SHA-256;
- compiled registration-plan SHA-256.

`build_windows_scm_installation_target(...)` fails closed if the manifest identity, binary identity, plan identity, or service name disagree.

`WindowsScmInstallationAuthorizationStore` persists an authorization with:

- authorization ID;
- exact target identities above;
- operator audit label (`authorized_by`);
- issue time;
- expiry time;
- single-use consumption time.

Consumption occurs under a SQLite `BEGIN IMMEDIATE` transaction and fails closed for:

- missing authorization;
- expiry;
- replay/already-consumed authorization;
- service-name drift;
- manifest drift;
- binary drift;
- registration-plan drift.

This is an authorization record, not authentication of the human named in `authorized_by`. It does not provide RBAC, MFA, cryptographic operator signatures, credential resolution, or SCM mutation. A future mutating installer must consume this exact authorization before privileged calls are permitted.


## Backend-injected Windows installation transaction candidate

ACP now has a mutation-orchestration candidate that deliberately accepts an injected backend instead of calling real SCM APIs.

`WindowsScmServiceInstallationTransaction` enforces this order:

1. validate the exact service/manifest/plan target;
2. validate required credential plumbing exists;
3. consume the exact single-use installation authorization;
4. only then call the backend to open SCM;
5. create the service;
6. configure delayed auto-start only when the admitted plan requires it;
7. on post-create configuration failure, attempt service deletion rollback;
8. close service and SCM handles in all paths.

Credential handling:

- only plans that explicitly require credential resolution invoke the resolver;
- the resolver receives the opaque credential reference;
- plaintext secret is passed only to the backend create call;
- no secret field exists in the transaction result;
- ACP clears its local secret reference after use.

Failure behavior:

- plan drift fails before authorization consumption or backend access;
- missing resolver fails before authorization consumption;
- create failure consumes the authorization but performs no delete rollback because no service handle exists;
- post-create failure attempts delete rollback;
- rollback failure is surfaced separately and never hidden;
- consumed authorization cannot be replayed for a second backend attempt.

Operator-local Windows corroboration on the connected Windows 11 / Python 3.14.5 machine produced `8/8 PASS`.

This slice still does not implement a native SCM mutation backend. Therefore no service was created, changed, deleted, started, or installed by this candidate.


## Native Windows SCM installation backend candidate

ACP now has a concrete native backend for the already-accepted authorized Windows installation transaction.

The backend maps the transaction protocol to:

- `OpenSCManagerW` with the exact compiled SCM access mask;
- `CreateServiceW` with the exact compiled service name, display name, access mask, service type, start type, error control, binary command, dependencies, account, and optional resolved credential;
- `ChangeServiceConfig2W(SERVICE_CONFIG_DELAYED_AUTO_START_INFO)` when delayed auto-start is explicitly present in the admitted plan;
- `DeleteService` for transaction rollback after post-create configuration failure;
- `CloseServiceHandle` for both service and SCM handles.

It preserves the accepted transaction ordering: exact authorization is consumed before the first native backend call, resolved credential material is not returned in transaction results, and rollback/handle cleanup remain owned by the transaction layer.

The native backend itself does not issue authorization and does not bypass manifest, binary-identity, plan, or authorization checks.

### Evidence boundary

Tests use an injected API object for mutation-call sequencing. Windows CI and operator-local Windows runs verify the native exports and ctypes ABI only; they do not create or modify a service.

This does **not** yet establish:
- a successful real `CreateServiceW` mutation;
- crash-safe mutation journaling;
- recovery from process death between create/configure/rollback;
- real credential retrieval;
- service-account ACL correctness;
- reboot persistence;
- production installation.


## Crash-safe Windows installation mutation journal candidate

ACP now has an append-only SQLite journal for the authorized Windows service installation transaction.

The journal records exact target identity and ordered durable states including:

- prepared;
- authorization consumed;
- SCM opened;
- create intent recorded;
- service created;
- configure intent recorded;
- delayed auto-start configured;
- rollback delete intent recorded;
- completed / failed / rolled back / rollback failed.

The transaction persists intent **before** each irreversible service mutation:

- create intent before `CreateServiceW`;
- configure intent before `ChangeServiceConfig2W`;
- rollback-delete intent before `DeleteService`.

Abrupt process death therefore cannot be reported as a false clean result. Recovery assessment is deliberately fail-closed:

- pre-mutation states classify as safe/no-service-mutation;
- completed installs classify clean-installed;
- completed rollback classifies clean-rolled-back;
- create/configure/delete ambiguity becomes `HOLD_POSSIBLE_INSTALLED_SERVICE`;
- rollback failure becomes `HOLD_ROLLBACK_FAILED`.

Tests explicitly use abrupt `SystemExit` during create/configure so normal exception rollback does not run, then reopen the SQLite journal and require the ambiguous HOLD classification.

This establishes durable mutation intent and recovery classification only. It does **not** yet inspect live SCM state to resolve an ambiguous hold, automatically resume configuration, automatically delete a possibly-created service, or authorize recovery mutation.


## Read-only Windows SCM recovery inspection candidate

ACP now has a candidate reconciliation layer above the accepted crash-safe installation journal.

`WindowsScmInstallRecoveryInspector` compares live service state to the exact admitted installation target and registration plan. An observed service is an exact match only when all of the following match:

- service name;
- display name;
- binary command;
- service type;
- start type;
- error control;
- dependency MULTI_SZ;
- account name;
- actual on-disk binary SHA-256.

The configured binary path is extracted from the observed service command and re-hashed during inspection. If hashing fails, inspection is a mismatch rather than a presumed match.

`WindowsScmNativeReadOnlyInspector` uses only:
- `OpenSCManagerW`;
- `OpenServiceW`;
- `QueryServiceConfigW`;
- `CloseServiceHandle`.

Windows error 1060 is interpreted as service absence; other native errors are surfaced.

The recovery resolver combines journal disposition + live inspection into bounded decisions such as:

- clean installed;
- clean rolled back;
- new install authorization required;
- hold exact service present;
- hold identity conflict;
- hold expected service missing.

Every resolution sets `cleanup_mutation_authorized = false`. This layer never deletes, modifies, starts, or stops a Windows service.

### Boundary

This establishes read-only recovery reconciliation only. It does **not** establish:
- cleanup/recovery authorization;
- recovery deletion or repair;
- automatic resolution of ambiguous CreateService/DeleteService outcomes;
- service-account ACL correctness;
- production installation recovery.

Until exact-head CI is green, this remains candidate evidence.
