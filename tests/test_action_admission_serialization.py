import json

from agent_control_plane.action_admission import ActionIntent
from agent_control_plane.action_admission_serialization import (
    action_intent_to_dict,
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
from agent_control_plane.action_admission import assess_action_intent


def test_action_intent_serialization_is_json_safe():
    intent = ActionIntent(
        intent_id="intent-json-1",
        principal_id="agent-1",
        capability="tool.calendar",
        resource_id="calendar:team",
        resource_type="calendar",
        operation="create_event",
        side_effect_class="MUTATING",
        context_id="session-1",
    )

    payload = action_intent_to_dict(intent)

    assert payload["intent_id"] == "intent-json-1"
    assert payload["context_id"] == "session-1"
    assert json.loads(json.dumps(payload))["operation"] == "create_event"


def test_admission_receipt_serialization_uses_reason_value_and_check_map():
    intent = ActionIntent(
        intent_id="intent-json-2",
        principal_id="agent-1",
        capability="tool.calendar",
        resource_id="calendar:team",
        resource_type="calendar",
        operation="create_event",
    )
    authority = AuthorityEnvelope(
        authority_id="auth-json-1",
        principal=PrincipalIdentity("agent-1", "agent"),
        capability="tool.calendar",
        resource=ResourceScope("calendar:team", "calendar"),
        operation=Operation("create_event"),
        policy=PolicyIdentity("policy-json-1", "v1"),
        decision=DecisionRecord("decision-json-1", DecisionOutcome.ALLOW, "approved"),
        expires_at="2030-01-01T00:00:00Z",
    )
    receipt = assess_action_intent(
        intent,
        authority,
        observed_at="2029-01-01T00:00:00Z",
        revocation_checker=lambda authority_id, observed_at: False,
    )

    payload = admission_receipt_to_dict(receipt)

    assert payload["admitted"] is True
    assert payload["reason_code"] == "ADMITTED"
    assert payload["checks"]["revocation"] is True
    assert payload["execution_enabled"] is False
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["schema_version"].endswith("v0-candidate")
