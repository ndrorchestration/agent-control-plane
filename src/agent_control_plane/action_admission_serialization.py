"""JSON-safe serialization helpers for Action Admission v0 records."""

from __future__ import annotations

from typing import Any

from .action_admission import ActionIntent, AdmissionReceipt


def action_intent_to_dict(intent: ActionIntent) -> dict[str, Any]:
    if not isinstance(intent, ActionIntent):
        raise TypeError("intent must be ActionIntent")
    return {
        "intent_id": intent.intent_id,
        "principal_id": intent.principal_id,
        "capability": intent.capability,
        "resource_id": intent.resource_id,
        "resource_type": intent.resource_type,
        "operation": intent.operation,
        "side_effect_class": intent.side_effect_class,
        "context_id": intent.context_id,
    }


def admission_receipt_to_dict(receipt: AdmissionReceipt) -> dict[str, Any]:
    if not isinstance(receipt, AdmissionReceipt):
        raise TypeError("receipt must be AdmissionReceipt")
    return {
        "admitted": receipt.admitted,
        "reason_code": receipt.reason_code.value,
        "intent_id": receipt.intent_id,
        "authority_id": receipt.authority_id,
        "decision_id": receipt.decision_id,
        "policy_id": receipt.policy_id,
        "observed_at": receipt.observed_at,
        "checks": {
            "principal": receipt.principal_checked,
            "capability": receipt.capability_checked,
            "resource": receipt.resource_checked,
            "operation": receipt.operation_checked,
            "lease": receipt.lease_checked,
            "revocation": receipt.revocation_checked,
            "delegation": receipt.delegation_checked,
            "conditions": receipt.conditions_checked,
            "state": receipt.state_checked,
        },
        "state_reason": receipt.state_reason,
        "execution_enabled": receipt.execution_enabled,
        "schema_version": receipt.schema_version,
    }
