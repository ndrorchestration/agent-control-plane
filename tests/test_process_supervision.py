import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.process_supervision import (
    ProcessFailureState,
    ProcessSupervisionDecision,
    ProcessSupervisionPolicy,
)


def test_restart_allowed_within_budget():
    policy = ProcessSupervisionPolicy(
        max_restarts=3,
        min_restart_interval_seconds=5,
    )
    state = ProcessFailureState(
        process_id="relay-a",
        failure_count=1,
        last_failure_at="2026-09-25T21:00:00Z",
    )
    assert policy.decide(
        state,
        now="2026-09-25T21:00:01Z",
    ) is ProcessSupervisionDecision.RESTART


def test_recent_restart_causes_hold():
    policy = ProcessSupervisionPolicy(
        max_restarts=3,
        min_restart_interval_seconds=10,
    )
    state = ProcessFailureState(
        process_id="relay-a",
        failure_count=2,
        last_failure_at="2026-09-25T21:00:05Z",
        last_restart_at="2026-09-25T21:00:00Z",
    )
    assert policy.decide(
        state,
        now="2026-09-25T21:00:05Z",
    ) is ProcessSupervisionDecision.HOLD


def test_restart_allowed_after_spacing_interval():
    policy = ProcessSupervisionPolicy(
        max_restarts=3,
        min_restart_interval_seconds=10,
    )
    state = ProcessFailureState(
        process_id="relay-a",
        failure_count=2,
        last_failure_at="2026-09-25T21:00:11Z",
        last_restart_at="2026-09-25T21:00:00Z",
    )
    assert policy.decide(
        state,
        now="2026-09-25T21:00:11Z",
    ) is ProcessSupervisionDecision.RESTART


def test_failure_count_beyond_budget_gives_up():
    policy = ProcessSupervisionPolicy(max_restarts=2)
    state = ProcessFailureState(
        process_id="relay-b",
        failure_count=3,
        last_failure_at="2026-09-25T21:00:00Z",
    )
    assert policy.decide(
        state,
        now="2026-09-25T21:00:01Z",
    ) is ProcessSupervisionDecision.GIVE_UP


def test_zero_restart_budget_gives_up_on_first_failure():
    policy = ProcessSupervisionPolicy(max_restarts=0)
    state = ProcessFailureState(
        process_id="relay-c",
        failure_count=1,
        last_failure_at="2026-09-25T21:00:00Z",
    )
    assert policy.decide(
        state,
        now="2026-09-25T21:00:01Z",
    ) is ProcessSupervisionDecision.GIVE_UP


def test_policy_validation():
    with pytest.raises(AuthorityValidationError):
        ProcessSupervisionPolicy(max_restarts=-1)
    with pytest.raises(AuthorityValidationError):
        ProcessSupervisionPolicy(min_restart_interval_seconds=-1)
