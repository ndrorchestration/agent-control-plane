# ACP Current Development Frontier — 2026-09-27

This page is the current-facing development overlay for Agent Control Plane
(ACP). Dated audit and evidence documents remain historical records and should
not be rewritten to imply later state.

## Accepted mainline state

Accepted typed read-only feature baseline from PR #93:

`e27a4fa1a5f351eb3a142744be3579eeac4e900c`

PR #93 replaced new signed read-only shell-text requests with a typed operation
contract. The accepted read-only path now uses:

```text
signed typed operation intent
  -> operation-specific parameter validation
  -> device / freshness / durable replay checks
  -> executor-owned allowed-root validation
  -> fixed argv derivation
  -> shell=False bounded execution
  -> typed result evidence bound to exact request-envelope SHA-256
```

The operation registry is immutable at runtime. Callers cannot create new
capability by relabeling arbitrary command text.

Exact-head #93 GitHub Actions completed successfully across Python 3.10–3.14.
An isolated local verification also reproduced 116 focused passing tests / 2
skipped and 640 full-suite passing tests / 11 skipped.

## Active non-executing mutation-control stack

Remote mutation execution is still blocked. The current development frontier is
split into three stacked draft PRs so each semantic transition can be reviewed
independently.

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

Verification:

- 49 focused tests PASS;
- 653 full-suite tests PASS / 11 skipped;
- GitHub Actions SUCCESS.

### PR #95 — mutation transaction model

Head:

`b0e475c97653d697d16ece3f7aa57b2e16b9a9e8`

Adds an immutable initial mutation-operation registry:

- `repo.write_text_file`;
- `repo.delete_file`.

The transaction plan binds request, authority, resource, operation, structured
parameters, expected precondition SHA-256, rollback SHA-256, and canonical plan
SHA-256.

Invariants:

```text
mutation_executed=false
execution_enabled=false
```

Verification:

- 58 focused tests PASS;
- 662 full-suite tests PASS / 11 skipped;
- GitHub Actions SUCCESS.

### PR #96 — authority / exact-plan composition

Head:

`79d130c032a86cf76961198ab5891a289360d055`

Binds the admitted intent to the exact prepared transaction so request,
authority, resource, operation, or plan substitution cannot silently occur
after admission. It also requires verified preconditions and rollback identity.

Invariants:

```text
mutation_executed=false
execution_enabled=false
```

Local verification:

- 65 focused tests PASS;
- 669 full-suite tests PASS / 11 skipped;
- compileall PASS.

GitHub Actions for exact head `79d130c032a86cf76961198ab5891a289360d055`
completed SUCCESS.

## Dependency chain

```text
accepted typed read-only execution (#93)
  -> mutation authority admission (#94 draft)
  -> mutation transaction model (#95 draft)
  -> exact admission/plan composition (#96 draft)
  -> operation-specific mutation safety
  -> rollback/postcondition/crash-recovery evidence
  -> separate live mutation-execution authorization
  -> only then consider an RDC mutation executor
```

## Next bounded engineering gate

Before any live mutation execution is considered, ACP must establish
operation-specific mutation safety for the tiny registry. At minimum this means:

- path containment and normalized target identity;
- symlink/junction/reparse-point handling;
- Git repository metadata and worktree boundary checks;
- exact creation/update/delete preconditions;
- rollback-material custody and content identity;
- postcondition verification;
- crash/interruption journal semantics;
- result/evidence binding to authority + plan + execution identity.

These controls should remain testable without performing a real remote mutation
until a separate mutation-execution gate is explicitly authorized.

## Evidence boundary

The current repository evidence does not establish:

- arbitrary command execution;
- live remote mutation authority or execution;
- authenticated remote transport identity;
- TPM/hardware-rooted device attestation;
- trusted external time;
- externally trusted key custody;
- production security or production readiness;
- general cross-runtime portability;
- DGAF High-Assurance authorization;
- independent validation;
- scientific efficacy or scientific-N increment.

ACP engineering evidence must remain separate from DGAF scientific/evidence-state
promotion and from claims made by any consuming research workload.
