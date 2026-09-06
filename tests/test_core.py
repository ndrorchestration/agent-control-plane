from agent_control_plane import ControlPlane, Task, TaskState


def test_dispatch_completes_and_records_events():
    plane = ControlPlane(run_id="run-test")
    plane.register("echo", lambda task: task.payload)

    task = plane.dispatch("echo", Task(payload="hello"))

    assert task.state is TaskState.COMPLETED
    assert task.result == "hello"
    assert [event.event for event in plane.events] == ["task.started", "task.completed"]
    assert all(event.run_id == "run-test" for event in plane.events)


def test_handler_failure_becomes_failed_state():
    plane = ControlPlane()
    plane.register("fail", lambda task: 1 / 0)

    task = plane.dispatch("fail", Task(payload=None))

    assert task.state is TaskState.FAILED
    assert task.error.startswith("ZeroDivisionError:")
    assert plane.events[-1].event == "task.failed"


def test_unknown_capability_is_rejected_and_recorded():
    plane = ControlPlane(run_id="run-reject")
    task = Task(payload=None)

    try:
        plane.dispatch("missing", task)
    except KeyError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("dispatch should reject an unknown capability")

    assert plane.events[-1].event == "task.rejected"
    assert plane.events[-1].task_id == task.id
    assert plane.events[-1].run_id == "run-reject"


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


def test_duplicate_capability_registration_is_rejected():
    plane = ControlPlane()
    plane.register("echo", lambda task: task.payload)

    try:
        plane.register("echo", lambda task: task.payload)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate registration should fail closed")


def test_provenance_manifest_binds_run_and_events():
    plane = ControlPlane(run_id="run-manifest")
    plane.register("echo", lambda task: task.payload)
    task = Task(payload="hello", id="task-fixed")
    plane.dispatch("echo", task)

    manifest = plane.provenance_manifest()

    assert manifest["schema"] == "agent-control-plane.provenance.v1"
    assert manifest["run_id"] == "run-manifest"
    assert manifest["event_count"] == 2
    assert [event["task_id"] for event in manifest["events"]] == ["task-fixed", "task-fixed"]
    assert all(event["run_id"] == "run-manifest" for event in manifest["events"])
