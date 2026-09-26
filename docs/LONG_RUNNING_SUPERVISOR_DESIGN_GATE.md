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
