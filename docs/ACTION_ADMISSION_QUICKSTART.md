# Action Admission v0 — Quickstart

Status: candidate API. The admission layer is non-executing and does not prove production authorization.

## Install

The current candidate ships inside the ACP package:

```bash
python -m pip install -e .
```

A standalone package/repository is intentionally deferred until external use justifies the split.

## Minimal use

```python
from agent_control_plane.action_admission import (
    ActionIntent,
    assess_action_intent,
)
from agent_control_plane.action_admission_serialization import (
    admission_receipt_to_dict,
)
from agent_control_plane.authority import (
    AuthorityEnvelope,
    DecisionOutcome,
    DecisionRecord,
    Operation,
    PolicyIdentity,
    PrincipalIdentity,
    ResourceScope,
)

intent = ActionIntent(
    intent_id="request-42",
    principal_id="assistant-1",
    capability="tool.calendar",
    resource_id="calendar:team",
    resource_type="calendar",
    operation="create_event",
)

authority = AuthorityEnvelope(
    authority_id="authority-7",
    principal=PrincipalIdentity("assistant-1", "agent"),
    capability="tool.calendar",
    resource=ResourceScope("calendar:team", "calendar"),
    operation=Operation("create_event"),
    policy=PolicyIdentity("policy-calendar", "v1"),
    decision=DecisionRecord(
        "decision-7",
        DecisionOutcome.ALLOW,
        "approved",
    ),
    expires_at="2030-01-01T00:00:00Z",
)

receipt = assess_action_intent(
    intent,
    authority,
    observed_at="2029-01-01T00:00:00Z",
    revocation_checker=lambda authority_id, observed_at: False,
)

print(admission_receipt_to_dict(receipt))
```

The result is a JSON-safe receipt containing:

- admitted / denied;
- stable reason code;
- intent / authority / decision / policy identities;
- which checks were performed;
- optional authority-state reason;
- schema version;
- `execution_enabled: false`.

## Important integration rule

The caller owns the external facts. Action Admission does not invent them.

For real integration, supply trustworthy implementations for:

- revocation checking;
- delegation evaluation when delegated authority is used;
- condition evaluation when conditional authority is used;
- state freshness when the caller requires it.

Checker failure is fail-closed.

## Request adapters

The candidate includes thin request-shape adapters:

- ACP `RemoteMutationIntent` → shared `ActionIntent`;
- generic `ToolCallRequest` → shared `ActionIntent`.

These adapters translate records only. They do not evaluate authority or execute actions.

## Claim ceiling

An admitted receipt means:

> Under the supplied local inputs and configured checkers, the intent satisfied the declared Action Admission v0 contract at the recorded observation time.

It does not prove authenticated identity, latest global authority state, durable revocation, cryptographic delegation, successful execution, causal effect, security certification, legal/regulatory compliance, or system-wide safety.

## Current validation state

The implementation candidate is exercised by the repository test matrix across Python 3.10–3.14. The generic tool-call adapter is an initial second-consumer conformance case. Neither fact establishes external-runtime portability or production readiness.
