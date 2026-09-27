# ACP Current Development Frontier — 2026-09-27

This page is the current-facing development overlay for Agent Control Plane
(ACP). Dated audit and evidence documents remain historical records and should
not be rewritten to imply later state.

## Accepted mainline state

Accepted typed read-only feature baseline from PR #93:

`e27a4fa1a5f351eb3a142744be3579eeac4e900c`

PR #93 replaced new signed read-only shell-text requests with a typed operation
contract. The accepted read-only path uses typed operation intent, validated
parameters, executor-owned allowed roots, fixed argv, `shell=False`, durable
replay checks, bounded output/runtime, and typed result evidence bound to the
exact request-envelope SHA-256.

Exact-head #93 GitHub Actions completed successfully across Python 3.10–3.14.
An isolated local verification also reproduced 116 focused passing tests / 2
skipped and 640 full-suite passing tests / 11 skipped.

## Independent bounded-execution frontier

### PR #97 — task-budget checkpoint/resume

Head:

`7782227a9b912b429cf8bb5f17ca98cc99b61eff`

This draft is independent of the remote-mutation stack. It adds a candidate
task-budget checkpoint/resume contract that preserves budget ceilings and
already-consumed usage while restoring a fresh `CREATED` task from
caller-supplied payload.

Verification:

- 23 focused tests PASS;
- 695 full-suite tests PASS / 6 skipped;
- compileall PASS;
- `git diff --check` PASS;
- GitHub Actions SUCCESS.

It does not establish durable checkpoint storage, authentication,
authorization, replay protection, distributed ownership, hidden runtime-state
restoration, or parent/child budget conservation.

## Active non-executing mutation-control stack

Remote mutation execution remains blocked. The mutation frontier is deliberately
stacked so each semantic transition can be reviewed independently.

### PR #94 — mutation authority admission

Head:

`15aed6f1bae08750d60e994d5c88777942e3b309`

Requires exact principal, `remote.mutation` capability, resource ID/type,
operation ID, authority lease, revocation state, delegation scope/evaluator,
and unconditional `ALLOW` alignment.

Invariant:

```text
execution_enabled=false
```

Verification: 49 focused PASS; 653 full-suite PASS / 11 skipped; GitHub Actions
SUCCESS.

### PR #95 — mutation transaction model

Head:

`b0e475c97653d697d16ece3f7aa57b2e16b9a9e8`

Adds the immutable initial mutation registry `repo.write_text_file` and
`repo.delete_file`, plus exact structured parameters, precondition SHA-256,
rollback SHA-256, and canonical plan SHA-256.

Invariants:

```text
mutation_executed=false
execution_enabled=false
```

Verification: 58 focused PASS; 662 full-suite PASS / 11 skipped; GitHub Actions
SUCCESS.

### PR #96 — authority / exact-plan composition

Head:

`79d130c032a86cf76961198ab5891a289360d055`

Binds the admitted intent to the exact prepared transaction so request,
authority, resource, operation, or plan substitution cannot silently occur
after admission.

Verification: 65 focused PASS; 669 full-suite PASS / 11 skipped; GitHub Actions
SUCCESS.

### PR #98 — repository mutation path safety

Head:

`91bd411ac60826de9d930655783795989394f48b`

Adds a non-executing repository path-safety gate after #96. It binds path
inspection to the admitted composition and exact plan SHA-256, preserves exact
path spelling, rejects traversal/absolute paths/drive syntax/control
characters/NTFS ADS/reserved device names/ambiguous spaces or dots/`.git`
segments, verifies resolved-root containment, rejects symlink target/ancestors,
and enforces operation-specific target/parent requirements.

This tranche also fixes a security-relevant plan-identity issue: transaction
parameter normalization had stripped path whitespace before hashing. The path
is now preserved exactly and filesystem canonicalization/rejection is owned by
the path-safety layer.

Invariants remain:

```text
mutation_executed=false
execution_enabled=false
```

Verification: 54 stacked mutation tests PASS / 1 skipped; 726 full-suite tests
PASS / 7 skipped; compileall and `git diff --check` PASS; GitHub Actions
SUCCESS.

### PR #101 — rollback material custody admission

Head:

`6d7dfacf3eeecd115d58b946d38f6e470acb6326`

Adds deterministic rollback-material description and custody/read-back
admission after #98. It binds rollback mode and descriptor SHA-256 to the
transaction plan:

- existing write → restore prior bytes;
- new write → delete newly created file;
- delete → restore prior bytes and bind the prior-content SHA-256.

The admission also binds an opaque custody reference, custody-object SHA-256,
observed read-back SHA-256, and exact upstream request/resource/operation/plan
identity.

Verification: 69 stacked mutation tests PASS / 1 skipped; 741 full-suite tests
PASS / 7 skipped; compileall and `git diff --check` PASS; GitHub Actions
SUCCESS.

Strong boundaries remain: ACP does not write custody material in this tranche;
custody is caller-observed evidence rather than independent storage
attestation; no rollback execution, mutation execution, postcondition
verification, crash recovery, execution receipt, or mutation-execution
authorization is established.

## Mutation dependency chain

```text
accepted typed read-only execution (#93)
  -> mutation authority admission (#94 draft)
  -> mutation transaction model (#95 draft)
  -> exact admission/plan composition (#96 draft)
  -> repository path safety (#98 draft)
  -> rollback material custody admission (#101 draft)
  -> postcondition verification
  -> crash/interruption journal + recovery
  -> execution receipt/result binding
  -> separate live mutation-execution authorization
  -> only then consider an RDC mutation executor
```

## Next bounded engineering gates

Two independent lines are now active:

1. Review/adjudicate the bounded task-budget checkpoint/resume draft #97.
2. Continue the mutation stack only with non-executing postcondition
   verification, then crash/interruption recovery and execution-evidence
   contracts.

A live Remote Desktop Commander mutation executor remains out of scope until a
separate explicit execution-authorization gate is designed, tested, and
accepted.

## Evidence boundary

The current repository evidence does not establish:

- arbitrary command execution;
- live remote mutation authority or execution;
- authenticated remote transport identity;
- TPM/hardware-rooted device attestation;
- trusted external time;
- externally trusted key or rollback custody;
- production security or production readiness;
- general cross-runtime portability;
- DGAF High-Assurance authorization;
- independent validation;
- scientific efficacy or scientific-N increment.

ACP engineering evidence must remain separate from DGAF scientific/evidence-state
promotion and from claims made by any consuming research workload.
