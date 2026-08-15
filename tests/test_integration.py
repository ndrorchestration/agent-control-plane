from agent_control_plane import ControlPlane, Task, TaskState


def test_policy_routing_lifecycle_and_provenance_together():
    plane = ControlPlane()
    plane.register("echo", lambda task: task.payload.upper())

    task = Task(payload="hello")
    result = plane.dispatch("echo", task)

    assert result.state is TaskState.COMPLETED
    assert result.result == "HELLO"
    assert [event.event for event in plane.events] == ["task.started", "task.completed"]
    assert plane.events[0].capability == "echo"
    assert plane.events[1].state == "completed"
    assert plane.events[0].timestamp


def test_failed_execution_produces_terminal_provenance():
    plane = ControlPlane()
    plane.register("fail", lambda task: (_ for _ in ()).throw(RuntimeError("boom")))

    result = plane.dispatch("fail", Task(payload=None))

    assert result.state is TaskState.FAILED
    assert plane.events[-1].event == "task.failed"
    assert plane.events[-1].detail == "RuntimeError: boom"
