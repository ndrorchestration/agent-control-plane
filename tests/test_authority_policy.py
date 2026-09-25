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
from agent_control_plane.authority_policy import AuthorityPolicy
from agent_control_plane.authority_state import (
    AuthorityStateRequirement,
    AuthorityStateSnapshot,
    AuthorityStateStatus,
    InMemoryAuthorityStateCache,
)
from agent_control_plane.revocation import InMemoryRevocationRegistry, RevocationRecord


def envelope(*, capability="read", outcome=DecisionOutcome.ALLOW, expires_at="2026-09-25T15:00:00Z", conditions=(), delegation=None):
    return AuthorityEnvelope(
        authority_id="auth-1",
        principal=PrincipalIdentity("principal-1", "agent"),
        capability=capability,
        resource=ResourceScope("resource-1", "document"),
        operation=Operation("inspect"),
        policy=PolicyIdentity("policy-1", "v1"),
        decision=DecisionRecord("decision-1", outcome, "test_reason"),
        expires_at=expires_at,
        conditions=conditions,
        delegation=delegation,
    )


def policy_for(authority, *, observed_at="2026-09-25T14:00:00Z", condition_evaluator=None):
    return AuthorityPolicy(
        resolver=lambda capability, task: authority,
        observed_at=lambda capability, task: observed_at,
        condition_evaluator=condition_evaluator,
    )


def dispatch_with(policy, capability="read"):
    plane = ControlPlane(policy=policy, run_id="run-authority")
    plane.register(capability, lambda task: "ok")
    task = plane.dispatch(capability, Task(payload={"resource_id": "resource-1"}))
    return plane, task


def test_allow_envelope_allows_existing_dispatch_path():
    plane, task = dispatch_with(policy_for(envelope()))
    assert task.state is TaskState.COMPLETED
    assert task.result == "ok"
    assert [event.event for event in plane.events] == ["task.started", "task.completed"]


def test_missing_authority_fails_closed_before_execution():
    plane, task = dispatch_with(policy_for(None))
    assert task.state is TaskState.CREATED
    assert task.result is None
    assert task.error == "authority missing"
    assert plane.events[-1].event == "task.denied"


def test_capability_mismatch_fails_closed():
    plane, task = dispatch_with(policy_for(envelope(capability="write")))
    assert task.state is TaskState.CREATED
    assert task.error == "authority capability mismatch"
    assert plane.events[-1].event == "task.denied"


def test_expired_authority_fails_closed():
    plane, task = dispatch_with(
        policy_for(envelope(expires_at="2026-09-25T14:00:00Z"), observed_at="2026-09-25T14:00:00Z")
    )
    assert task.state is TaskState.CREATED
    assert task.error == "authority lease invalid or expired"
    assert plane.events[-1].event == "task.denied"


def test_explicit_deny_fails_closed_with_reason_code():
    plane, task = dispatch_with(policy_for(envelope(outcome=DecisionOutcome.DENY)))
    assert task.state is TaskState.CREATED
    assert task.error == "authority denied:test_reason"
    assert plane.events[-1].event == "task.denied"


def test_conditional_authority_requires_evaluator():
    item = envelope(outcome=DecisionOutcome.CONDITIONAL, conditions=("human_approved",))
    plane, task = dispatch_with(policy_for(item))
    assert task.error == "authority conditions unresolved"
    assert plane.events[-1].event == "task.denied"


def test_conditional_authority_allows_only_explicit_true():
    item = envelope(outcome=DecisionOutcome.CONDITIONAL, conditions=("human_approved",))
    _, allowed = dispatch_with(policy_for(item, condition_evaluator=lambda authority, capability, task: True))
    assert allowed.state is TaskState.COMPLETED

    plane, denied = dispatch_with(policy_for(item, condition_evaluator=lambda authority, capability, task: False))
    assert denied.state is TaskState.CREATED
    assert denied.error == "authority conditions unsatisfied"
    assert plane.events[-1].event == "task.denied"


def test_resolver_and_time_errors_fail_closed():
    resolver_policy = AuthorityPolicy(
        resolver=lambda capability, task: (_ for _ in ()).throw(RuntimeError("boom")),
        observed_at=lambda capability, task: "2026-09-25T14:00:00Z",
    )
    _, resolver_task = dispatch_with(resolver_policy)
    assert resolver_task.error == "authority resolution failed"

    time_policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _, time_task = dispatch_with(time_policy)
    assert time_task.error == "authority time resolution failed"


def test_non_utc_observation_time_fails_closed():
    _, task = dispatch_with(policy_for(envelope(), observed_at="2026-09-25T10:00:00-04:00"))
    assert task.error == "authority lease invalid or expired"


def test_revoked_authority_fails_closed_at_and_after_revocation_time():
    registry = InMemoryRevocationRegistry()
    registry.revoke(RevocationRecord("auth-1", "2026-09-25T14:00:00Z", "operator_revoked"))
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T14:00:00Z",
        revocation_checker=registry.is_revoked_at,
    )
    plane, task = dispatch_with(policy)
    assert task.state is TaskState.CREATED
    assert task.error == "authority revoked"
    assert plane.events[-1].event == "task.denied"


def test_authority_before_revocation_time_is_not_retroactively_denied():
    registry = InMemoryRevocationRegistry()
    registry.revoke(RevocationRecord("auth-1", "2026-09-25T14:00:00Z", "operator_revoked"))
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T13:59:59Z",
        revocation_checker=registry.is_revoked_at,
    )
    _, task = dispatch_with(policy)
    assert task.state is TaskState.COMPLETED


def test_revocation_checker_error_fails_closed():
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T14:00:00Z",
        revocation_checker=lambda authority_id, observed_at: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _, task = dispatch_with(policy)
    assert task.error == "authority revocation check failed"


def test_delegated_authority_requires_explicit_delegation_evaluator():
    from agent_control_plane.authority import Delegation
    item = envelope(delegation=Delegation("owner-1", ("read",)))
    _, unresolved = dispatch_with(policy_for(item))
    assert unresolved.error == "authority delegation unresolved"

    allow_policy = AuthorityPolicy(
        resolver=lambda capability, task: item,
        observed_at=lambda capability, task: "2026-09-25T14:00:00Z",
        delegation_evaluator=lambda authority, capability, task: True,
    )
    _, allowed = dispatch_with(allow_policy)
    assert allowed.state is TaskState.COMPLETED

    deny_policy = AuthorityPolicy(
        resolver=lambda capability, task: item,
        observed_at=lambda capability, task: "2026-09-25T14:00:00Z",
        delegation_evaluator=lambda authority, capability, task: False,
    )
    _, denied = dispatch_with(deny_policy)
    assert denied.error == "authority delegation invalid"


def test_delegation_evaluator_error_fails_closed():
    from agent_control_plane.authority import Delegation
    item = envelope(delegation=Delegation("owner-1", ("read",)))
    policy = AuthorityPolicy(
        resolver=lambda capability, task: item,
        observed_at=lambda capability, task: "2026-09-25T14:00:00Z",
        delegation_evaluator=lambda authority, capability, task: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _, task = dispatch_with(policy)
    assert task.error == "authority delegation evaluation failed"


def state_checker(cache, requirement):
    def check(authority, observed_at):
        result = cache.evaluate(authority.authority_id, observed_at, requirement)
        if result.status is AuthorityStateStatus.CURRENT:
            return None
        return result.status.value
    return check


def test_missing_authority_state_fails_closed():
    cache = InMemoryAuthorityStateCache()
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T14:05:00Z",
        state_freshness_checker=state_checker(cache, AuthorityStateRequirement(1, 300)),
    )
    plane, task = dispatch_with(policy)
    assert task.state is TaskState.CREATED
    assert task.error == "authority state stale:missing"
    assert plane.events[-1].event == "task.denied"


def test_stale_epoch_fails_closed_even_when_recent():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:04:59Z", "node-a"))
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T14:05:00Z",
        state_freshness_checker=state_checker(cache, AuthorityStateRequirement(2, 300)),
    )
    _, task = dispatch_with(policy)
    assert task.error == "authority state stale:stale_epoch"


def test_stale_age_fails_closed_even_when_epoch_is_current():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:00:00Z", "node-a"))
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T14:05:01Z",
        state_freshness_checker=state_checker(cache, AuthorityStateRequirement(2, 300)),
    )
    _, task = dispatch_with(policy)
    assert task.error == "authority state stale:stale_age"


def test_current_authority_state_allows_dispatch():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:00:00Z", "node-a"))
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T14:05:00Z",
        state_freshness_checker=state_checker(cache, AuthorityStateRequirement(2, 300)),
    )
    _, task = dispatch_with(policy)
    assert task.state is TaskState.COMPLETED


def test_authority_state_checker_error_fails_closed():
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T14:05:00Z",
        state_freshness_checker=lambda authority, observed_at: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _, task = dispatch_with(policy)
    assert task.error == "authority state check failed"
