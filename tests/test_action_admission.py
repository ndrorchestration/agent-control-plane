from agent_control_plane.action_admission import (
    ActionIntent,
    AdmissionReason,
    assess_action_intent,
)
from agent_control_plane.authority import (
    AuthorityEnvelope,
    DecisionOutcome,
    DecisionRecord,
    Delegation,
    Operation,
    PolicyIdentity,
    PrincipalIdentity,
    ResourceScope,
)


def intent(**overrides):
    values = {
        "intent_id": "intent-1",
        "principal_id": "principal-1",
        "capability": "tool.write",
        "resource_id": "resource-1",
        "resource_type": "document",
        "operation": "update",
        "side_effect_class": "MUTATING",
        "context_id": "ctx-1",
    }
    values.update(overrides)
    return ActionIntent(**values)


def authority(
    *,
    outcome=DecisionOutcome.ALLOW,
    expires_at="2030-01-01T00:00:00Z",
    conditions=(),
    delegation=None,
    **overrides,
):
    values = {
        "authority_id": "auth-1",
        "principal": PrincipalIdentity("principal-1", "agent"),
        "capability": "tool.write",
        "resource": ResourceScope("resource-1", "document"),
        "operation": Operation("update"),
        "policy": PolicyIdentity("policy-1", "v1"),
        "decision": DecisionRecord("decision-1", outcome, "approved"),
        "expires_at": expires_at,
        "conditions": conditions,
        "delegation": delegation,
    }
    values.update(overrides)
    return AuthorityEnvelope(**values)


def assess(i=None, a=None, **kwargs):
    return assess_action_intent(
        i or intent(),
        authority() if a is None else a,
        observed_at=kwargs.pop("observed_at", "2029-01-01T00:00:00Z"),
        revocation_checker=kwargs.pop(
            "revocation_checker", lambda authority_id, observed_at: False
        ),
        **kwargs,
    )


def test_exact_binding_admits_without_enabling_execution():
    result = assess()
    assert result.admitted is True
    assert result.reason_code is AdmissionReason.ADMITTED
    assert result.execution_enabled is False
    assert result.principal_checked is True
    assert result.capability_checked is True
    assert result.resource_checked is True
    assert result.operation_checked is True
    assert result.lease_checked is True
    assert result.revocation_checked is True


def test_missing_authority_fails_closed():
    result = assess(a=False)
    assert result.admitted is False
    assert result.reason_code is AdmissionReason.AUTHORITY_MISSING_OR_INVALID
    assert result.execution_enabled is False


def test_principal_mismatch_fails_closed():
    result = assess(
        a=authority(principal=PrincipalIdentity("someone-else", "agent"))
    )
    assert result.reason_code is AdmissionReason.PRINCIPAL_MISMATCH


def test_capability_mismatch_fails_closed():
    result = assess(a=authority(capability="tool.read"))
    assert result.reason_code is AdmissionReason.CAPABILITY_MISMATCH


def test_resource_mismatch_fails_closed():
    result = assess(a=authority(resource=ResourceScope("other", "document")))
    assert result.reason_code is AdmissionReason.RESOURCE_MISMATCH


def test_operation_mismatch_fails_closed():
    result = assess(a=authority(operation=Operation("delete")))
    assert result.reason_code is AdmissionReason.OPERATION_MISMATCH


def test_expired_lease_fails_closed():
    result = assess(a=authority(expires_at="2028-01-01T00:00:00Z"))
    assert result.reason_code is AdmissionReason.LEASE_INVALID_OR_EXPIRED


def test_non_utc_observation_time_fails_closed():
    result = assess(observed_at="2029-01-01T00:00:00-04:00")
    assert result.reason_code is AdmissionReason.LEASE_INVALID_OR_EXPIRED


def test_revoked_authority_fails_closed():
    result = assess(revocation_checker=lambda authority_id, observed_at: True)
    assert result.reason_code is AdmissionReason.AUTHORITY_REVOKED


def test_revocation_checker_exception_fails_closed():
    def broken(authority_id, observed_at):
        raise RuntimeError("unavailable")

    result = assess(revocation_checker=broken)
    assert result.reason_code is AdmissionReason.REVOCATION_CHECK_FAILED


def test_delegation_scope_mismatch_fails_closed():
    item = authority(delegation=Delegation("owner-1", ("other",)))
    result = assess(
        a=item, delegation_evaluator=lambda supplied_authority, supplied_intent: True
    )
    assert result.reason_code is AdmissionReason.DELEGATION_SCOPE_MISMATCH


def test_delegation_requires_explicit_evaluator():
    item = authority(delegation=Delegation("owner-1", ("update",)))
    result = assess(a=item)
    assert result.reason_code is AdmissionReason.DELEGATION_UNRESOLVED


def test_invalid_delegation_fails_closed():
    item = authority(delegation=Delegation("owner-1", ("update",)))
    result = assess(
        a=item, delegation_evaluator=lambda supplied_authority, supplied_intent: False
    )
    assert result.reason_code is AdmissionReason.DELEGATION_INVALID


def test_valid_delegation_can_admit():
    item = authority(delegation=Delegation("owner-1", ("update",)))
    result = assess(
        a=item, delegation_evaluator=lambda supplied_authority, supplied_intent: True
    )
    assert result.admitted is True
    assert result.delegation_checked is True
    assert result.execution_enabled is False


def test_conditional_authority_requires_explicit_evaluator():
    item = authority(
        outcome=DecisionOutcome.CONDITIONAL,
        conditions=("human_approved",),
    )
    result = assess(a=item)
    assert result.reason_code is AdmissionReason.CONDITIONS_UNRESOLVED


def test_failed_conditions_fail_closed():
    item = authority(
        outcome=DecisionOutcome.CONDITIONAL,
        conditions=("human_approved",),
    )
    result = assess(
        a=item,
        condition_evaluator=lambda supplied_authority, supplied_intent: False,
    )
    assert result.reason_code is AdmissionReason.CONDITIONS_UNSATISFIED


def test_satisfied_conditional_authority_can_admit():
    item = authority(
        outcome=DecisionOutcome.CONDITIONAL,
        conditions=("human_approved",),
    )
    result = assess(
        a=item,
        condition_evaluator=lambda supplied_authority, supplied_intent: True,
    )
    assert result.admitted is True
    assert result.conditions_checked is True
    assert result.execution_enabled is False


def test_deny_outcome_fails_closed():
    result = assess(a=authority(outcome=DecisionOutcome.DENY))
    assert result.reason_code is AdmissionReason.OUTCOME_NOT_ALLOW


def test_state_checker_exception_fails_closed():
    def broken(supplied_authority, observed_at):
        raise RuntimeError("unavailable")

    result = assess(state_freshness_checker=broken)
    assert result.reason_code is AdmissionReason.STATE_CHECK_FAILED
    assert result.state_checked is True


def test_stale_state_fails_closed_with_reason():
    result = assess(
        state_freshness_checker=lambda supplied_authority, observed_at: "stale_epoch"
    )
    assert result.reason_code is AdmissionReason.STATE_STALE
    assert result.state_reason == "stale_epoch"
    assert result.state_checked is True


def test_current_state_can_admit():
    result = assess(
        state_freshness_checker=lambda supplied_authority, observed_at: None
    )
    assert result.admitted is True
    assert result.state_checked is True


def test_action_intent_is_framework_neutral_and_does_not_require_acp_task():
    item = ActionIntent(
        intent_id="tool-call-17",
        principal_id="assistant-7",
        capability="calendar.create",
        resource_id="calendar:team",
        resource_type="calendar",
        operation="create_event",
    )
    assert item.intent_id == "tool-call-17"
    assert not hasattr(item, "task_id")
    assert not hasattr(item, "run_id")
