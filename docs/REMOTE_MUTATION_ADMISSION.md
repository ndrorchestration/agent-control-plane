# Remote Mutation Admission Candidate

Status: **NON-EXECUTING / FAIL-CLOSED / CANDIDATE ENGINEERING CONTRACT**.

## Purpose

Define the minimum authority congruence ACP must be able to prove before any
future remote mutation executor is even considered.

This tranche does **not** add a mutation executor, mutation operation registry,
or mutating Remote Desktop Commander path.

## Required bindings

A mutation intent is eligible for future execution design review only when the
supplied authority envelope matches all of the following exactly:

- principal identity;
- `remote.mutation` capability;
- resource ID and resource type;
- operation ID;
- unexpired authority lease at the supplied observation time;
- explicit revocation check returning not revoked;
- delegation scope, when delegation exists;
- explicit delegation evaluator acceptance, when delegation exists;
- unconditional `ALLOW` decision.

Conditional authority remains unresolved in this initial tranche rather than
being inferred safe.

## Strong non-effect

Every `RemoteMutationAdmissionRecord` contains:

```text
execution_enabled=false
```

Even an `admitted=true` record means only that the authority bindings required
by this candidate contract were satisfied. It cannot execute a mutation and is
not execution authorization by itself.

## Why this is separate from AuthorityPolicy

The existing generic `AuthorityPolicy` deliberately does not infer
resource/operation fit. Remote mutation requires those bindings to be explicit
and exact, so this candidate keeps the stronger mutation-specific admission
semantics separate rather than silently widening the generic policy adapter.

## Deliberately not established

- mutation execution;
- filesystem/repository write operation registry;
- rollback or transactional mutation semantics;
- remote endpoint authentication;
- hardware-rooted device identity;
- trusted external time;
- independent signer/key custody;
- production security;
- DGAF High-Assurance authorization;
- independent validation or scientific efficacy.
