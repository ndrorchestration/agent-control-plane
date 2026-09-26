# Long-Running Supervisor Design Gate

Status: **DESIGN CONTRACT — UNBOUNDED DAEMON NOT AUTHORIZED**

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

- [ ] lifecycle state machine tests PASS;
- [ ] SIGTERM graceful-shutdown test PASS;
- [ ] SIGINT graceful-shutdown test PASS;
- [ ] repeated-signal idempotence test PASS;
- [ ] child crash during shutdown test PASS;
- [ ] multi-worker ownership-conflict tests PASS;
- [ ] restart forbidden after stop-request test PASS;
- [ ] persistent ownership/restart state defined and tested;
- [ ] bounded concurrency semantics defined;
- [ ] executable/privilege policy defined;
- [ ] finite integration test proves startup -> run -> signal -> clean stop;
- [ ] exact evidence boundary documented.

Until those gates are satisfied:

**LONG_RUNNING_SUPERVISOR = NOT AUTHORIZED**


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
