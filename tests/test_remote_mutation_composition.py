from agent_control_plane.authority import (
    AuthorityEnvelope,
    DecisionOutcome,
    DecisionRecord,
    Operation,
    PolicyIdentity,
    PrincipalIdentity,
    ResourceScope,
)
from agent_control_plane.remote_mutation_admission import RemoteMutationIntent, assess_remote_mutation_intent
from agent_control_plane.remote_mutation_composition import compose_mutation_admission_and_plan
from agent_control_plane.remote_mutation_transaction import MutationPlan, prepare_mutation_transaction

A = "a" * 64
B = "b" * 64
C = "c" * 64


def fixture():
    intent = RemoteMutationIntent(
        request_id="req-1",
        principal_id="operator-1",
        device_id="device-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
    )
    authority = AuthorityEnvelope(
        authority_id="auth-1",
        principal=PrincipalIdentity("operator-1", "human"),
        capability="remote.mutation",
        resource=ResourceScope("repo:acp", "git_repository"),
        operation=Operation("repo.write_text_file"),
        policy=PolicyIdentity("policy-1", "v1"),
        decision=DecisionRecord("decision-1", DecisionOutcome.ALLOW, "approved"),
        expires_at="2030-01-01T00:00:00Z",
    )
    admission = assess_remote_mutation_intent(
        intent,
        authority,
        observed_at="2029-01-01T00:00:00Z",
        revocation_checker=lambda authority_id, observed_at: False,
    )
    plan = MutationPlan(
        request_id="req-1",
        authority_id="auth-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={"path": "docs/example.md", "content_sha256": C},
        precondition_sha256=A,
        rollback_sha256=B,
    )
    transaction = prepare_mutation_transaction(
        plan,
        observed_precondition_sha256=A,
        observed_rollback_sha256=B,
    )
    return intent, admission, plan, transaction


def test_exact_composition_is_admitted_but_nonexecuting():
    intent, admission, plan, transaction = fixture()
    result = compose_mutation_admission_and_plan(intent, admission, plan, transaction)
    assert result.admitted is True
    assert result.execution_enabled is False
    assert result.mutation_executed is False
    assert result.plan_sha256 == plan.plan_sha256


def test_denied_admission_blocks_composition():
    intent, admission, plan, transaction = fixture()
    denied = admission.__class__(
        admitted=False,
        reason="authority revoked",
        request_id=admission.request_id,
        authority_id=admission.authority_id,
        decision_id=admission.decision_id,
        policy_id=admission.policy_id,
        principal_checked=True,
        capability_checked=True,
        resource_checked=True,
        operation_checked=True,
        lease_checked=True,
        revocation_checked=True,
        delegation_checked=False,
    )
    result = compose_mutation_admission_and_plan(intent, denied, plan, transaction)
    assert result.admitted is False
    assert "authority admission" in result.reason


def test_plan_substitution_by_request_id_is_blocked():
    intent, admission, plan, transaction = fixture()
    substituted = MutationPlan(
        request_id="req-other",
        authority_id=plan.authority_id,
        resource_id=plan.resource_id,
        resource_type=plan.resource_type,
        operation_id=plan.operation_id,
        parameters=plan.parameters,
        precondition_sha256=plan.precondition_sha256,
        rollback_sha256=plan.rollback_sha256,
    )
    result = compose_mutation_admission_and_plan(intent, admission, substituted, transaction)
    assert result.admitted is False
    assert "request_id" in result.reason


def test_plan_substitution_by_authority_is_blocked():
    intent, admission, plan, transaction = fixture()
    substituted = MutationPlan(
        request_id=plan.request_id,
        authority_id="auth-other",
        resource_id=plan.resource_id,
        resource_type=plan.resource_type,
        operation_id=plan.operation_id,
        parameters=plan.parameters,
        precondition_sha256=plan.precondition_sha256,
        rollback_sha256=plan.rollback_sha256,
    )
    result = compose_mutation_admission_and_plan(intent, admission, substituted, transaction)
    assert result.admitted is False
    assert "authority_id" in result.reason


def test_plan_substitution_by_operation_is_blocked():
    intent, admission, plan, transaction = fixture()
    substituted = MutationPlan(
        request_id=plan.request_id,
        authority_id=plan.authority_id,
        resource_id=plan.resource_id,
        resource_type=plan.resource_type,
        operation_id="repo.delete_file",
        parameters={"path": "docs/example.md", "prior_content_sha256": C},
        precondition_sha256=plan.precondition_sha256,
        rollback_sha256=plan.rollback_sha256,
    )
    result = compose_mutation_admission_and_plan(intent, admission, substituted, transaction)
    assert result.admitted is False
    assert "operation_id" in result.reason


def test_transaction_plan_digest_mismatch_is_blocked():
    intent, admission, plan, transaction = fixture()
    other_plan = MutationPlan(
        request_id=plan.request_id,
        authority_id=plan.authority_id,
        resource_id=plan.resource_id,
        resource_type=plan.resource_type,
        operation_id=plan.operation_id,
        parameters={"path": "docs/other.md", "content_sha256": C},
        precondition_sha256=plan.precondition_sha256,
        rollback_sha256=plan.rollback_sha256,
    )
    result = compose_mutation_admission_and_plan(intent, admission, other_plan, transaction)
    assert result.admitted is False
    assert "transaction.plan_sha256" in result.reason


def test_unverified_preconditions_block_composition():
    intent, admission, plan, _ = fixture()
    blocked = prepare_mutation_transaction(
        plan,
        observed_precondition_sha256=C,
        observed_rollback_sha256=B,
    )
    result = compose_mutation_admission_and_plan(intent, admission, plan, blocked)
    assert result.admitted is False
    assert "preconditions" in result.reason
