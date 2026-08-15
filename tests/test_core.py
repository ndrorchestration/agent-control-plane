from agent_control_plane import ControlPlane, Task, TaskState


def test_dispatch_completes_and_records_events():
    plane = ControlPlane()
    plane.register("echo", lambda task: task.payload)

    task = plane.dispatch("echo", Task(payload="hello"))

    assert task.state is TaskState.COMPLETED
    assert task.result == "hello"
    assert [event.event for event in plane.events] == ["task.started", "task.completed"]


def test_handler_failure_becomes_failed_state():
    plane = ControlPlane()
    plane.register("fail", lambda task: 1 / 0)

    task = plane.dispatch("fail", Task(payload=None))

    assert task.state is TaskState.FAILED
    assert task.error.startswith("ZeroDivisionError:")
    assert plane.events[-1].event == "task.failed"


def test_unknown_capability_is_rejected():
    plane = ControlPlane()

    try:
        plane.dispatch("missing", Task(payload=None))
    except KeyError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("dispatch should reject an unknown capability")


def test_cancel_created_task():
    plane = ControlPlane()
    task = plane.cancel(Task(payload="work"))

    assert task.state is TaskState.CANCELLED
    assert plane.events[-1].event == "task.cancelled"


def test_completed_task_cannot_be_dispatched_again():
    plane = ControlPlane()
    plane.register("echo", lambda task: task.payload)
    task = plane.dispatch("echo", Task(payload="x"))

    try:
        plane.dispatch("echo", task)
    except ValueError as exc:
        assert "not dispatchable" in str(exc)
    else:
        raise AssertionError("terminal tasks must not be redispatched")
