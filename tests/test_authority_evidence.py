from agent_control_plane import ControlPlane, Task, TaskState
from agent_control_plane.authority import (
    AuthorityEnvelope,
    DecisionOutcome,
    DecisionRecord,
    Operation,
    PolicyIdentity,
    PrincipalIdentity,
    ResourceScope,
)
from agent_control_plane.authority_evidence import EvidenceAuthorityPolicy
from agent_control_plane.authority_policy import AuthorityPolicy
from agent_control_plane.authority_state import (
    AuthorityStateRequirement,
    AuthorityStateSnapshot,
    AuthorityStateStatus,
    InMemoryAuthorityStateCache,
)
from agent_control_plane.revocation import InMemoryRevocationRegistry, RevocationRecord


def envelope(*, outcome=DecisionOutcome.ALLOW, expires_at="2026-09-25T15:00:00Z"):
    return AuthorityEnvelope(
        authority_id="auth-1",
        principal=PrincipalIdentity("principal-1", "agent"),
        capability="read",
        resource=ResourceScope("resource-1", "document"),
        operation=Operation("inspect"),
        policy=PolicyIdentity("policy-1", "v1"),
        decision=DecisionRecord("decision-1", outcome, "test_reason"),
        expires_at=expires_at,
    )


def wrapped_policy(item, *, run_id="run-evidence", observed_at="2026-09-25T14:00:00Z", revocation_checker=None):
    policy = AuthorityPolicy(
        resolver=lambda capability, task: item,
        observed_at=lambda capability, task: observed_at,
        revocation_checker=revocation_checker,
    )
    return EvidenceAuthorityPolicy(policy, run_id=run_id)


def dispatch(policy):
    plane = ControlPlane(policy=policy, run_id=policy.run_id)
    plane.register("read", lambda task: "ok")
    task = Task(payload={"resource_id": "resource-1"}, id="task-1")
    result = plane.dispatch("read", task)
    return plane, result


def test_allowed_dispatch_records_authority_decision_identity():
    policy = wrapped_policy(envelope())
    plane, task = dispatch(policy)
    assert task.state is TaskState.COMPLETED
    record = policy.get("task-1")
    assert record is not None
    assert record.run_id == "run-evidence"
    assert record.capability == "read"
    assert record.allowed is True
    assert record.authority_id == "auth-1"
    assert record.decision_id == "decision-1"
    assert record.policy_id == "policy-1"
    assert record.outcome == "allow"
    assert record.reason_code == "test_reason"
    assert record.observed_at == "2026-09-25T14:00:00Z"
    assert plane.events[-1].event == "task.completed"


def test_denied_dispatch_records_decision_and_denial_reason():
    policy = wrapped_policy(envelope(outcome=DecisionOutcome.DENY))
    plane, task = dispatch(policy)
    assert task.state is TaskState.CREATED
    record = policy.get("task-1")
    assert record is not None
    assert record.allowed is False
    assert record.denial_reason == "authority denied:test_reason"
    assert record.outcome == "deny"
    assert plane.events[-1].event == "task.denied"


def test_revocation_check_is_reflected_in_decision_evidence():
    registry = InMemoryRevocationRegistry()
    registry.revoke(RevocationRecord("auth-1", "2026-09-25T14:00:00Z", "operator_revoked"))
    policy = wrapped_policy(envelope(), revocation_checker=registry.is_revoked_at)
    _, task = dispatch(policy)
    assert task.error == "authority revoked"
    record = policy.get("task-1")
    assert record is not None
    assert record.revocation_checked is True
    assert record.allowed is False


def test_manifest_is_run_bound_and_deterministically_sorted_by_task_id():
    policy = wrapped_policy(envelope())
    plane = ControlPlane(policy=policy, run_id=policy.run_id)
    plane.register("read", lambda task: "ok")
    plane.dispatch("read", Task(payload=None, id="task-b"))
    plane.dispatch("read", Task(payload=None, id="task-a"))
    manifest = policy.manifest()
    assert manifest["schema"] == "agent-control-plane.authority-decision-evidence.v0-candidate"
    assert manifest["run_id"] == "run-evidence"
    assert manifest["record_count"] == 2
    assert [item["task_id"] for item in manifest["records"]] == ["task-a", "task-b"]


def test_wrapper_rejects_blank_run_id_and_wrong_policy_type():
    import pytest
    with pytest.raises(ValueError, match="run_id"):
        EvidenceAuthorityPolicy(AuthorityPolicy(
            resolver=lambda capability, task: envelope(),
            observed_at=lambda capability, task: "2026-09-25T14:00:00Z",
        ), run_id=" ")
    with pytest.raises(TypeError, match="AuthorityPolicy"):
        EvidenceAuthorityPolicy(lambda capability, task: None, run_id="run-1")


def test_state_freshness_check_is_reflected_in_decision_evidence():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:00:00Z", "node-a"))

    def freshness(authority, observed_at):
        result = cache.evaluate(authority.authority_id, observed_at, AuthorityStateRequirement(2, 300))
        return None if result.status is AuthorityStateStatus.CURRENT else result.status.value

    policy = EvidenceAuthorityPolicy(
        AuthorityPolicy(
            resolver=lambda capability, task: envelope(),
            observed_at=lambda capability, task: "2026-09-25T14:05:00Z",
            state_freshness_checker=freshness,
        ),
        run_id="run-evidence",
    )
    _, task = dispatch(policy)
    assert task.error == "authority state stale:stale_epoch"
    record = policy.get("task-1")
    assert record is not None
    assert record.state_checked is True
    assert record.state_reason == "stale_epoch"
