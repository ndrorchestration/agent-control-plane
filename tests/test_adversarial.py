from agent_control_plane import ControlPlane, Task, TaskState


def test_empty_capability_is_rejected_without_execution():
    plane = ControlPlane()
    called = False

    def handler(task):
        nonlocal called
        called = True
        return task.payload

    try:
        plane.register("   ", handler)
    except ValueError:
        pass
    else:
        raise AssertionError("blank capability must be rejected")

    assert called is False
    assert plane.events == []


def test_handler_failure_preserves_single_terminal_failure_event():
    plane = ControlPlane()
    plane.register("fail", lambda task: (_ for _ in ()).throw(RuntimeError("boom")))

    task = plane.dispatch("fail", Task(payload="x"))

    assert task.state is TaskState.FAILED
    assert len(plane.events) == 2
    assert plane.events[0].event == "task.started"
    assert plane.events[1].event == "task.failed"
    assert plane.events[1].detail == "RuntimeError: boom"


def test_policy_is_checked_before_started_event():
    plane = ControlPlane(policy=lambda capability, task: "blocked")
    plane.register("echo", lambda task: task.payload)

    task = plane.dispatch("echo", Task(payload="x"))

    assert task.state is TaskState.CREATED
    assert [event.event for event in plane.events] == ["task.denied"]


def test_provenance_event_order_is_deterministic_for_success():
    plane = ControlPlane()
    plane.register("echo", lambda task: task.payload)

    plane.dispatch("echo", Task(payload="one"))
    plane.dispatch("echo", Task(payload="two"))

    assert [event.event for event in plane.events] == [
        "task.started", "task.completed", "task.started", "task.completed"
    ]
