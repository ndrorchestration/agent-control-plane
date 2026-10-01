from agent_control_plane.action_admission import AdmissionReason, assess_action_intent
from agent_control_plane.action_admission_adapters import (
    ToolCallRequest,
    remote_mutation_to_action_intent,
    tool_call_to_action_intent,
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
from agent_control_plane.remote_mutation_admission import RemoteMutationIntent


def authority_for(
    *,
    principal_id,
    capability,
    resource_id,
    resource_type,
    operation,
):
    return AuthorityEnvelope(
        authority_id="auth-portability-1",
        principal=PrincipalIdentity(principal_id, "agent"),
        capability=capability,
        resource=ResourceScope(resource_id, resource_type),
        operation=Operation(operation),
        policy=PolicyIdentity("policy-portability-1", "v1"),
        decision=DecisionRecord("decision-portability-1", DecisionOutcome.ALLOW, "approved"),
        expires_at="2030-01-01T00:00:00Z",
    )


def test_acp_remote_mutation_adapter_uses_shared_core_without_execution():
    remote = RemoteMutationIntent(
        request_id="remote-1",
        principal_id="operator-1",
        device_id="device-1",
        resource_id="repo:demo",
        resource_type="git_repository",
        operation_id="repo.write_file",
    )
    action = remote_mutation_to_action_intent(remote)
    auth = authority_for(
        principal_id="operator-1",
        capability="remote.mutation",
        resource_id="repo:demo",
        resource_type="git_repository",
        operation="repo.write_file",
    )

    result = assess_action_intent(
        action,
        auth,
        observed_at="2029-01-01T00:00:00Z",
        revocation_checker=lambda authority_id, observed_at: False,
    )

    assert result.admitted is True
    assert result.reason_code is AdmissionReason.ADMITTED
    assert result.execution_enabled is False
    assert action.context_id == "device-1"


def test_generic_tool_call_adapter_uses_same_core_contract():
    request = ToolCallRequest(
        request_id="tool-1",
        actor_id="assistant-1",
        tool_name="calendar",
        action="create_event",
        target_id="calendar:team",
        target_type="calendar",
        side_effect_class="MUTATING",
        context_id="session-1",
    )
    action = tool_call_to_action_intent(request)
    auth = authority_for(
        principal_id="assistant-1",
        capability="tool.calendar",
        resource_id="calendar:team",
        resource_type="calendar",
        operation="create_event",
    )

    result = assess_action_intent(
        action,
        auth,
        observed_at="2029-01-01T00:00:00Z",
        revocation_checker=lambda authority_id, observed_at: False,
    )

    assert result.admitted is True
    assert result.reason_code is AdmissionReason.ADMITTED
    assert result.execution_enabled is False
    assert action.context_id == "session-1"


def test_generic_tool_call_mismatch_fails_with_shared_reason_semantics():
    request = ToolCallRequest(
        request_id="tool-2",
        actor_id="assistant-1",
        tool_name="calendar",
        action="delete_event",
        target_id="calendar:team",
        target_type="calendar",
    )
    action = tool_call_to_action_intent(request)
    auth = authority_for(
        principal_id="assistant-1",
        capability="tool.calendar",
        resource_id="calendar:team",
        resource_type="calendar",
        operation="create_event",
    )

    result = assess_action_intent(
        action,
        auth,
        observed_at="2029-01-01T00:00:00Z",
        revocation_checker=lambda authority_id, observed_at: False,
    )

    assert result.admitted is False
    assert result.reason_code is AdmissionReason.OPERATION_MISMATCH
    assert result.execution_enabled is False
