from agent_control_plane import ControlPlane, Task, TaskState
from agent_control_plane.policy import evaluate_policy


def test_policy_allows_when_no_reason_returned():
    decision = evaluate_policy(lambda capability, task: None, "echo", Task(payload="x"))
    assert decision.allowed is True
    assert decision.reason is None


def test_policy_denies_with_explicit_reason():
    decision = evaluate_policy(lambda capability, task: "capability blocked", "shell", Task(payload="x"))
    assert decision.allowed is False
    assert decision.reason == "capability blocked"


def test_control_plane_blocks_denied_capability_before_execution():
    called = False

    def handler(task):
        nonlocal called
        called = True
        return "should not run"

    plane = ControlPlane(policy=lambda capability, task: "blocked")
    plane.register("echo", handler)

    task = plane.dispatch("echo", Task(payload="x"))

    assert called is False
    assert task.state is TaskState.CREATED
    assert task.error == "blocked"
    assert plane.events[-1].event == "task.denied"
