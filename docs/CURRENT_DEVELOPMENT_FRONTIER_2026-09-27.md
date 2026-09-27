# ACP Current Development Frontier — 2026-09-27

This is the current-facing development overlay for Agent Control Plane (ACP).
Dated audits and evidence documents remain historical records and are not
rewritten to imply later state.

## Accepted mainline

Observed `main` at this documentation checkpoint:

`e037e2b5ab3b519e9cd3e8171ababa22e1e6b115`

Accepted capabilities include:

- typed read-only remote execution from PR #93;
- bounded task-budget checkpoint/resume from merged PR #97.

The stable typed read-only feature baseline remains:

`e27a4fa1a5f351eb3a142744be3579eeac4e900c`

PR #97 merged with exact-head CI success after reconciliation onto current main.
Its checkpoint hash is content identity only; durable/authenticated storage,
replay protection, distributed ownership, hidden runtime-state restoration, and
parent/child budget conservation remain unestablished.

## Canonical mutation-control stack

The mutation stack remains **draft / non-executing**. All exact heads below
completed GitHub Actions successfully.

### #94 — mutation authority admission

Head:

`15aed6f1bae08750d60e994d5c88777942e3b309`

Binds principal, `remote.mutation` capability, resource ID/type, operation,
lease, revocation, delegation, and unconditional `ALLOW`.

Invariant:

```text
execution_enabled=false
```

### #95 — mutation transaction model

Head:

`b0e475c97653d697d16ece3f7aa57b2e16b9a9e8`

Adds immutable `repo.write_text_file` / `repo.delete_file` operation
definitions, canonical plan identity, precondition identity, and rollback
identity.

Invariants:

```text
execution_enabled=false
mutation_executed=false
```

### #96 — exact authority / plan composition

Head:

`79d130c032a86cf76961198ab5891a289360d055`

Prevents post-admission substitution of request, authority, resource,
operation, plan, prepared transaction, preconditions, or rollback identity.
### #98 — repository mutation path safety

Head:

`91bd411ac60826de9d930655783795989394f48b`

Adds exact repository-relative path safety, resolved-root containment,
symlink/junction/metadata defenses, operation-shape checks, and exact path
identity preservation.

### #101 — rollback-material custody admission

Head:

`6d7dfacf3eeecd115d58b946d38f6e470acb6326`

Binds deterministic rollback descriptors, custody reference, custody-object
SHA-256, read-back SHA-256, and exact upstream plan identity. Custody remains
caller-observed evidence, not independent storage attestation.

### #103 — read-only postcondition verification

Head:

`ef6bc823cc8cfdb6abcd9e4775eb1a99f95073d6`

Canonical postcondition lineage after reconciliation.

It:

- verifies planned write content by observed file SHA-256;
- verifies planned delete by target absence;
- revalidates repository boundary and symlink safety;
- requires observation root to equal the pre-execution path-safety root;
- requires observed resolved target to equal the pre-execution resolved target;
- carries rollback descriptor SHA-256 and custody reference forward.

Local canonicalization verification:

- 82 stacked mutation tests PASS / 1 skipped;
- 13 postcondition tests PASS.

Exact-head GitHub Actions: SUCCESS.

### #105 — durable mutation journal / recovery classification

Head:

`611a5678b9f034cfed8bd8c6a5ad0b1e212b471e`

Canonical recovery lineage after reconciliation with #103.

The journal distinguishes:

- prepared;
- execution intent recorded;
- external effect reported;
- postcondition verified;
- rollback intent recorded;
- rollback verified;
- failed.

It retains UTC chronology and evidence hashes and classifies restart/recovery
state fail-closed. Any recovery path requires fresh execution authorization.

Local canonicalization verification:

- 99 stacked mutation/recovery tests PASS / 1 skipped;
- 17 journal tests PASS.

Exact-head GitHub Actions: SUCCESS.

### #106 — execution/result-evidence binding

Head:

`c3ba51546faee1f6e592304aebc0cb92d3191ba7`

Binds caller-supplied external execution/result evidence to the exact plan,
journal transaction, external-effect event, verified postcondition, rollback
descriptor, and custody reference.

The receipt does **not** authenticate the external executor, prove causality, or
authorize another mutation.

Local canonicalization verification:

- 112 stacked tests PASS / 1 skipped;
- 13 execution-evidence tests PASS.

Exact-head GitHub Actions: SUCCESS.
### #108 — single-use mutation execution authorization + closure

Head:

`497b6eb1843a7f7936dd96f6f8278ca3d11048ce`

Adds an exact, expiring, SQLite-backed, single-use authorization contract for one
external mutation attempt plus post-execution closure binding.

Authorization requires the exact admitted composition, verified transaction
preconditions/rollback identity, path safety, rollback custody, PREPARED
journal state, executor ID, transaction ID, plan SHA-256, and issue/expiry
window.

Consumption is replay-protected across restart. Closure binds the consumed
authorization to the terminal evidence chain and authorizes no further
execution.

Local canonicalization verification:

- 133 stacked mutation tests PASS / 1 skipped;
- 21 authorization/closure tests PASS.

Exact-head GitHub Actions: SUCCESS.

## Superseded duplicate lineage

PR #104 and PR #107 are closed as **superseded**, not failed.

- #104's stronger postcondition identity findings were ported into canonical
  #103.
- #107's fail-closed recovery ideas were reconciled into the richer canonical
  #105 recovery state machine.

Keeping the duplicates closed avoids two competing postcondition/recovery APIs.

## Canonical dependency chain

```text
accepted typed read-only execution (#93)
  -> mutation authority admission (#94 draft)
  -> transaction / rollback planning (#95 draft)
  -> exact authority-plan composition (#96 draft)
  -> repository path safety (#98 draft)
  -> rollback-material custody admission (#101 draft)
  -> read-only postcondition verification (#103 draft)
  -> durable journal / recovery classification (#105 draft)
  -> execution/result-evidence binding (#106 draft)
  -> single-use exact-attempt authorization + closure (#108 draft)
  -> NO LIVE ACP/RDC MUTATION EXECUTOR YET
```

## Next bounded engineering work

Before a live mutation executor is considered, ACP still needs a separately
reviewed execution composition that:

- authenticates or otherwise establishes the executor identity assumed by the
  authorization contract;
- consumes the exact single-use authorization before the side effect;
- records execution intent durably before the side effect;
- restricts execution to the fixed typed mutation registry;
- preserves path and plan identity at effect time;
- records external-effect evidence without inferring success;
- performs read-only postcondition verification after the effect;
- enters recovery hold on ambiguous interruption;
- performs rollback only through a separately authorized recovery path;
- binds final evidence and closure without granting replay.

A simulation/dry-run harness should precede any live Remote Desktop Commander
mutation integration.

## Evidence boundary

The current evidence does **not** establish:

- a live ACP mutation executor;
- arbitrary command execution;
- authenticated remote executor identity;
- causal proof that ACP caused an observed mutation;
- hardware-rooted device attestation;
- trusted external time;
- independently trusted key or rollback custody;
- production security or production readiness;
- general cross-runtime portability;
- DGAF High-Assurance authorization;
- independent validation;
- scientific efficacy or scientific-N increment.

Draft contracts do not become accepted `main` capability merely because their
tests pass. ACP engineering evidence remains separate from DGAF
scientific/evidence-state promotion and from claims made by consuming research
workloads.
