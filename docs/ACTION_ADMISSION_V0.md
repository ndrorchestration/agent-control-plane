# Action Admission v0 — Extraction and Portability Specification

Controller: #146

## Status

SPECIFICATION ONLY. This document does not enable execution, modify `agent-control-plane.execution.v1`, or promote any mutation-capable draft into accepted behavior.

## Purpose

Extract the smallest reusable, framework-neutral admission contract already latent in ACP's authority and remote-mutation primitives.

Core abstraction:

```text
intent + authority + observation context
    -> admission decision + evidence receipt
```

ACP remains one consumer/adapter of the contract. The core must not depend on ACP's `Task` model, remote-mutation capability naming, execution kernel, or DGAF/PDMAL terminology.

## Records

### ActionIntent

Required:

- `intent_id`
- `principal_id`
- `capability`
- `resource_id`
- `resource_type`
- `operation`

Optional:

- `side_effect_class`
- `context_id`

### AuthorityEnvelope

Preserve the current candidate semantics:

- authority ID;
- principal identity;
- capability;
- resource scope;
- operation/action;
- policy identity and version/hash;
- decision identity;
- explicit decision outcome;
- reason code;
- lease expiry;
- optional conditions;
- optional delegation.

### AdmissionContext

Caller-supplied:

- UTC `observed_at`;
- revocation checker;
- optional delegation evaluator;
- optional condition evaluator;
- optional state-freshness checker.

The core does not invent external authority facts. It evaluates the values and checkers supplied by the caller.

### AdmissionReceipt

Required:

- admitted boolean;
- stable machine-readable reason code;
- intent ID;
- known authority/decision/policy IDs;
- observation time when resolved;
- check-performed flags for principal/capability/resource/operation/lease/revocation/delegation/conditions/state;
- optional state/freshness reason;
- schema version;
- explicit non-execution invariant.

For v0, admission must not enable or perform execution. An `execution_enabled=false` field or equivalent invariant is required.

## Stable reason codes

Initial set:

- `AUTHORITY_MISSING_OR_INVALID`
- `PRINCIPAL_MISMATCH`
- `CAPABILITY_MISMATCH`
- `RESOURCE_MISMATCH`
- `OPERATION_MISMATCH`
- `LEASE_INVALID_OR_EXPIRED`
- `REVOCATION_CHECK_FAILED`
- `AUTHORITY_REVOKED`
- `DELEGATION_SCOPE_MISMATCH`
- `DELEGATION_UNRESOLVED`
- `DELEGATION_INVALID`
- `CONDITIONS_UNRESOLVED`
- `CONDITIONS_UNSATISFIED`
- `STATE_CHECK_FAILED`
- `STATE_STALE`
- `OUTCOME_NOT_ALLOW`
- `ADMITTED`

Human-readable detail may be attached separately, but downstream logic should not depend on free-text reason strings.

## Evaluation order

1. validate intent shape;
2. validate authority shape;
3. principal binding;
4. capability binding;
5. resource binding;
6. operation binding;
7. lease validity at caller-supplied UTC time;
8. configured state freshness;
9. revocation;
10. delegation scope and evaluator when delegated;
11. conditional requirements and evaluator when conditional;
12. explicit decision outcome;
13. emit a non-executing receipt.

The evaluation order is observable because receipts record which checks were reached.

## Required fail-closed semantics

- Missing or malformed authority denies.
- Invalid/non-UTC observation time denies.
- External checker exceptions deny.
- The v0 admission path requires a revocation result.
- Delegation never self-validates from the presence of a delegation record.
- Delegated scope must include the exact operation.
- Conditional authority never self-promotes to allow.
- Configured missing/stale/future authority state denies.
- A check not performed must not be represented as successful.
- Admission must not execute, enqueue, retry, mutate, or imply an effect.

## What admission establishes

An admitted receipt means only:

> Under the supplied local inputs and configured checkers, the intent satisfied the declared Action Admission v0 contract at the recorded observation time.

It does not establish:

- authenticated principal identity;
- policy-signature validity;
- globally latest authority state;
- durable/distributed revocation;
- cryptographic delegation legitimacy;
- production authorization;
- successful execution;
- causal effect;
- security certification;
- legal/regulatory compliance;
- system-wide safety or reliability.

## ACP adapter requirements

ACP should adapt existing components rather than duplicate semantics:

- current `AuthorityEnvelope` -> core authority representation;
- current remote-mutation intent -> `ActionIntent`;
- current revocation/delegation/state logic -> injected checkers;
- core receipt -> ACP-local admission/evidence record.

This extraction must not modify `agent-control-plane.execution.v1`.

## Portability gate

Do not call the contract reusable until one materially different second-system adapter:

1. uses the same core schema;
2. uses the same reason codes;
3. passes the same conformance cases;
4. does not fork the core contract.

A simple non-mutating generic tool-call gate, local file-operation simulator, or mock MCP-style action request is sufficient for the first portability test.

## Minimum conformance cases

- exact binding admits;
- principal mismatch denies;
- capability mismatch denies;
- resource mismatch denies;
- operation mismatch denies;
- expired lease denies;
- revoked authority denies;
- revocation checker error denies;
- delegation scope mismatch denies;
- delegation without evaluator denies;
- invalid delegation denies;
- valid delegation can admit;
- conditional authority without evaluator denies;
- failed condition denies;
- satisfied condition can admit;
- configured missing/stale authority state denies;
- deny outcome denies;
- admitted receipt leaves execution disabled.

## Evidence boundary

Current ACP code already demonstrates bounded local implementations for typed authority envelopes, lease checks, revocation, delegation, conditional policy evaluation, state freshness, and non-executing mutation admission.

This specification does not establish production readiness, distributed correctness, security authorization, independent validation, or governance efficacy.
