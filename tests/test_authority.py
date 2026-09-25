import pytest

from agent_control_plane.authority import (
    AUTHORITY_SCHEMA_VERSION,
    AuthorityEnvelope,
    AuthorityValidationError,
    DecisionOutcome,
    DecisionRecord,
    Delegation,
    Operation,
    PolicyIdentity,
    PrincipalIdentity,
    ResourceScope,
)


def envelope(**overrides):
    values = {
        "authority_id": "auth-1",
        "principal": PrincipalIdentity("principal-1", "agent"),
        "capability": "read",
        "resource": ResourceScope("resource-1", "document"),
        "operation": Operation("inspect"),
        "policy": PolicyIdentity("policy-1", "sha256:abc123"),
        "decision": DecisionRecord("decision-1", DecisionOutcome.ALLOW, "policy_match"),
        "expires_at": "2026-09-25T15:00:00Z",
    }
    values.update(overrides)
    return AuthorityEnvelope(**values)


def test_authority_envelope_serializes_structured_semantics_deterministically():
    item = envelope(
        conditions=("read_only", "no_external_side_effects"),
        delegation=Delegation("human-owner", ("read", "inspect")),
    )
    assert item.to_dict()["schema_version"] == AUTHORITY_SCHEMA_VERSION
    assert item.to_dict()["principal"]["principal_id"] == "principal-1"
    assert item.to_dict()["resource"]["resource_id"] == "resource-1"
    assert item.to_dict()["operation"]["action"] == "inspect"
    assert item.to_dict()["policy"]["policy_id"] == "policy-1"
    assert item.to_dict()["decision"] == {
        "decision_id": "decision-1",
        "outcome": "allow",
        "reason_code": "policy_match",
    }
    assert item.to_dict()["delegation"] == {
        "delegator_id": "human-owner",
        "scope": ["read", "inspect"],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("authority_id", ""),
        ("capability", " "),
        ("expires_at", "2026-09-25T15:00:00"),
        ("expires_at", "2026-09-25T16:00:00+01:00"),
    ],
)
def test_authority_envelope_fails_closed_on_invalid_required_values(field, value):
    with pytest.raises(AuthorityValidationError):
        envelope(**{field: value})


def test_authority_envelope_rejects_wrong_nested_type():
    with pytest.raises(AuthorityValidationError, match="principal"):
        envelope(principal="not-a-principal")


def test_authority_envelope_rejects_unsupported_schema_version():
    with pytest.raises(AuthorityValidationError, match="schema_version"):
        envelope(schema_version="agent-control-plane.authority.v999")


def test_conditional_decision_requires_explicit_conditions():
    with pytest.raises(AuthorityValidationError, match="requires conditions"):
        envelope(
            decision=DecisionRecord(
                "decision-conditional",
                DecisionOutcome.CONDITIONAL,
                "requires_human_review",
            )
        )


def test_delegation_requires_nonempty_unique_scope():
    with pytest.raises(AuthorityValidationError, match="non-empty"):
        Delegation("owner", ())
    with pytest.raises(AuthorityValidationError, match="duplicates"):
        Delegation("owner", ("read", "read"))


def test_temporal_validity_is_explicit_and_fail_closed_at_expiry():
    item = envelope(expires_at="2026-09-25T15:00:00Z")
    assert item.is_valid_at("2026-09-25T14:59:59Z") is True
    assert item.is_valid_at("2026-09-25T15:00:00Z") is False
    with pytest.raises(AuthorityValidationError, match="expired"):
        item.assert_valid_at("2026-09-25T15:00:00Z")


def test_temporal_validity_rejects_non_utc_observation_time():
    item = envelope()
    with pytest.raises(AuthorityValidationError, match="UTC"):
        item.is_valid_at("2026-09-25T10:00:00-04:00")


def test_decision_record_requires_typed_outcome():
    with pytest.raises(AuthorityValidationError, match="DecisionOutcome"):
        DecisionRecord("decision-1", "allow", "policy_match")
