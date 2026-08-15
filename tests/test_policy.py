from agent_control_plane import Task
from agent_control_plane.policy import evaluate_policy


def test_policy_allows_when_no_reason_returned():
    decision = evaluate_policy(lambda capability, task: None, "echo", Task(payload="x"))
    assert decision.allowed is True
    assert decision.reason is None


def test_policy_denies_with_explicit_reason():
    decision = evaluate_policy(lambda capability, task: "capability blocked", "shell", Task(payload="x"))
    assert decision.allowed is False
    assert decision.reason == "capability blocked"
