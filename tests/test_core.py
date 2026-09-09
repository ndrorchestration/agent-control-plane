from agent_control_plane import (
    BudgetExceeded,
    ControlPlane,
    ExecutionBudget,
    Task,
    TaskState,
)


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


def test_budget_allows_exact_limit_and_records_usage():
    plane = ControlPlane(run_id="run-budget-ok")

    def handler(task):
        task.consume(steps=2, tool_calls=1, tokens=100, cost=0.25)
        return "ok"

    plane.register("work", handler)
    task = Task(
        payload=None,
        budget=ExecutionBudget(
            max_steps=2,
            max_tool_calls=1,
            max_tokens=100,
            max_cost=0.25,
        ),
    )

    result = plane.dispatch("work", task)

    assert result.state is TaskState.COMPLETED
    assert result.result == "ok"
    assert result.usage.steps == 2
    assert result.usage.tool_calls == 1
    assert result.usage.tokens == 100
    assert result.usage.cost == 0.25
    assert "steps=2" in plane.events[-1].detail


def test_budget_overrun_is_atomic_and_fails_closed():
    plane = ControlPlane(run_id="run-budget-fail")

    def handler(task):
        task.consume(steps=1)
        task.consume(steps=2)
        return "should-not-complete"

    plane.register("work", handler)
    task = Task(payload=None, budget=ExecutionBudget(max_steps=2))

    result = plane.dispatch("work", task)

    assert result.state is TaskState.BUDGET_EXHAUSTED
    assert result.result is None
    assert result.usage.steps == 1
    assert "steps budget exceeded" in result.error
    assert plane.events[-1].event == "task.budget_exhausted"


def test_handler_cannot_suppress_budget_failure_and_complete():
    plane = ControlPlane()

    def handler(task):
        try:
            task.consume(tool_calls=2)
        except BudgetExceeded:
            pass
        return "suppressed"

    plane.register("work", handler)
    task = Task(payload=None, budget=ExecutionBudget(max_tool_calls=1))

    result = plane.dispatch("work", task)

    assert result.state is TaskState.BUDGET_EXHAUSTED
    assert result.result is None
    assert result.usage.tool_calls == 0
    assert plane.events[-1].event == "task.budget_exhausted"


def test_unbudgeted_task_can_still_report_usage():
    plane = ControlPlane()

    def handler(task):
        task.consume(steps=3, tool_calls=2, tokens=50, cost=0.1)
        return task.usage.steps

    plane.register("work", handler)
    result = plane.dispatch("work", Task(payload=None))

    assert result.state is TaskState.COMPLETED
    assert result.result == 3
    assert result.usage.steps == 3


def test_invalid_budget_is_rejected_before_dispatch():
    for kwargs in (
        {"max_steps": -1},
        {"max_tool_calls": -1},
        {"max_tokens": -1},
        {"max_cost": -0.01},
    ):
        try:
            ExecutionBudget(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid budget should be rejected: {kwargs}")
