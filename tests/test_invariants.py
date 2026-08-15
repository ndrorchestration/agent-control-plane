from agent_control_plane import ControlPlane, Task, TaskState


def test_terminal_task_cannot_be_dispatched_again():
    plane = ControlPlane()
    plane.register("echo", lambda task: task.payload)
    task = plane.dispatch("echo", Task(payload="x"))

    try:
        plane.dispatch("echo", task)
    except ValueError as exc:
        assert "not dispatchable" in str(exc)
    else:
        raise AssertionError("terminal task must not be dispatched again")


def test_denied_task_remains_created_and_handler_is_not_called():
    called = False

    def handler(task):
        nonlocal called
        called = True
        return "unexpected"

    plane = ControlPlane(policy=lambda capability, task: "blocked")
    plane.register("echo", handler)
    task = plane.dispatch("echo", Task(payload="x"))

    assert task.state is TaskState.CREATED
    assert task.error == "blocked"
    assert called is False
    assert plane.events[-1].event == "task.denied"


def test_unknown_capability_does_not_change_task_state():
    plane = ControlPlane()
    task = Task(payload="x")

    try:
        plane.dispatch("missing", task)
    except KeyError:
        pass
    else:
        raise AssertionError("unknown capability should fail")

    assert task.state is TaskState.CREATED
    assert plane.events == []


def test_cancellation_is_terminal():
    plane = ControlPlane()
    task = plane.cancel(Task(payload="x"))

    assert task.state is TaskState.CANCELLED
    try:
        plane.cancel(task)
    except ValueError:
        pass
    else:
        raise AssertionError("cancelled task must not be cancelled again")
