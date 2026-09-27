# Remote Mutation End-to-End Adversarial Gate

Status: **NON-EXECUTING / INTEGRATION-EVIDENCE ONLY**.

This tranche composes the accepted candidate contracts from mutation authority
admission through single-use execution authorization and closure without adding
a live executor.

## Canonical dependency chain

```text
#94 authority admission
  -> #95 transaction / precondition / rollback model
  -> #96 exact authority-plan composition
  -> #98 repository path safety
  -> #101 rollback custody admission
  -> #103 postcondition verification
  -> #105 durable recovery journal
  -> #106 execution/result evidence binding
  -> #108 single-use execution authorization + closure
  -> this integration gate
```

Duplicate experimental branches #104 and #107 are superseded/closed and are not
part of the canonical chain.

## Adversarial scenarios

The integration test suite covers:

- one exact authorization consumed once, followed by journaled effect evidence,
  verified postcondition, execution-evidence binding, and closure;
- authorization replay after durable store reopen;
- expired authorization before execution intent;
- authorization consumption after execution intent, which must prevent closure;
- interruption after execution intent, which must remain
  `HOLD_AMBIGUOUS_EFFECT`;
- substituted external-effect evidence hash, which must prevent evidence binding.

## Strong non-effects

A passing integration suite does **not** establish a live mutation executor.

The test constructs the control/evidence records and journal transitions in
process. It does not call Remote Desktop Commander to write, delete, rename, or
otherwise mutate a repository.

The following remain unestablished:

- executor authenticity;
- transport authenticity;
- causal attribution of an external effect to ACP;
- atomic coupling between authorization consumption and a real side effect;
- TOCTOU resistance across a real remote execution boundary;
- rollback execution;
- production security;
- High-Assurance authorization;
- independent validation.

A future live-executor tranche must be separately authorized and must preserve
the exact plan, path, custody, journal, single-use authorization, evidence, and
closure semantics already established here.
