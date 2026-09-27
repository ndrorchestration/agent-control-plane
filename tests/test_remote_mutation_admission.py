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
from agent_control_plane.remote_mutation_admission import (
    RemoteMutationIntent,
    assess_remote_mutation_intent,
)


def intent(**overrides):
    values = {
        "request_id": "req-mutate-1",
        "principal_id": "operator-1",
        "device_id": "device-1",
        "resource_id": "repo:agent-control-plane",
        "resource_type": "git_repository",
        "operation_id": "repo.write_file",
    }
    values.update(overrides)
    return RemoteMutationIntent(**values)


def authority(*, outcome=DecisionOutcome.ALLOW, expires_at="2030-01-01T00:00:00Z", delegation=None, conditions=(), **overrides):
    values = {
        "authority_id": "auth-1",
        "principal": PrincipalIdentity("operator-1", "human"),
        "capability": "remote.mutation",
        "resource": ResourceScope("repo:agent-control-plane", "git_repository"),
        "operation": Operation("repo.write_file"),
        "policy": PolicyIdentity("policy-1", "sha256:example"),
        "decision": DecisionRecord("decision-1", outcome, "approved"),
        "expires_at": expires_at,
        "conditions": conditions,
        "delegation": delegation,
    }
    values.update(overrides)
    return AuthorityEnvelope(**values)


def assess(i=None, a=None, **kwargs):
    return assess_remote_mutation_intent(
        i or intent(),
        a or authority(),
        observed_at=kwargs.pop("observed_at", "2029-01-01T00:00:00Z"),
        revocation_checker=kwargs.pop("revocation_checker", lambda authority_id, observed_at: False),
        **kwargs,
    )


def test_exact_binding_is_admitted_but_never_enables_execution():
    result = assess()
    assert result.admitted is True
    assert result.execution_enabled is False
    assert result.reason == "authority bindings satisfied; mutation execution remains disabled"
    assert result.principal_checked is True
    assert result.resource_checked is True
    assert result.operation_checked is True
    assert result.revocation_checked is True


def test_principal_mismatch_fails_closed():
    result = assess(a=authority(principal=PrincipalIdentity("someone-else", "human")))
    assert result.admitted is False
    assert result.reason == "principal mismatch"


def test_capability_mismatch_fails_closed():
    result = assess(a=authority(capability="remote.read"))
    assert result.admitted is False
    assert result.reason == "capability mismatch"


def test_resource_mismatch_fails_closed():
    result = assess(a=authority(resource=ResourceScope("repo:other", "git_repository")))
    assert result.admitted is False
    assert result.reason == "resource mismatch"


def test_operation_mismatch_fails_closed():
    result = assess(a=authority(operation=Operation("repo.delete_file")))
    assert result.admitted is False
    assert result.reason == "operation mismatch"


def test_expired_authority_fails_closed():
    result = assess(a=authority(expires_at="2028-01-01T00:00:00Z"))
    assert result.admitted is False
    assert result.reason == "authority lease invalid or expired"


def test_revoked_authority_fails_closed():
    result = assess(revocation_checker=lambda authority_id, observed_at: True)
    assert result.admitted is False
    assert result.reason == "authority revoked"


def test_revocation_checker_error_fails_closed():
    def broken(authority_id, observed_at):
        raise RuntimeError("unavailable")

    result = assess(revocation_checker=broken)
    assert result.admitted is False
    assert result.reason == "revocation check failed"


def test_delegation_requires_scope_and_explicit_evaluator():
    delegated = authority(delegation=Delegation("delegator-1", ("repo.write_file",)))
    unresolved = assess(a=delegated)
    assert unresolved.admitted is False
    assert unresolved.reason == "delegation unresolved"

    invalid = assess(a=delegated, delegation_evaluator=lambda authority, mutation_intent: False)
    assert invalid.admitted is False
    assert invalid.reason == "delegation invalid"

    valid = assess(a=delegated, delegation_evaluator=lambda authority, mutation_intent: True)
    assert valid.admitted is True
    assert valid.execution_enabled is False


def test_delegation_scope_must_include_exact_operation():
    delegated = authority(delegation=Delegation("delegator-1", ("repo.other",)))
    result = assess(a=delegated, delegation_evaluator=lambda authority, mutation_intent: True)
    assert result.admitted is False
    assert result.reason == "delegation scope mismatch"


def test_conditional_authority_remains_unresolved_in_initial_tranche():
    result = assess(a=authority(outcome=DecisionOutcome.CONDITIONAL, conditions=("human_confirmation",)))
    assert result.admitted is False
    assert result.reason == "conditional mutation authority unresolved"


def test_deny_outcome_is_never_admitted():
    result = assess(a=authority(outcome=DecisionOutcome.DENY))
    assert result.admitted is False
    assert result.reason == "authority outcome not allow:deny"


def test_mutation_intent_requires_mutating_profile_and_capability():
    try:
        intent(expected_side_effect_class="READ_ONLY")
    except ValueError as exc:
        assert "MUTATING" in str(exc)
    else:
        raise AssertionError("READ_ONLY mutation intent should fail")

    try:
        intent(capability="remote.read")
    except ValueError as exc:
        assert "remote.mutation" in str(exc)
    else:
        raise AssertionError("non-mutation capability should fail")
