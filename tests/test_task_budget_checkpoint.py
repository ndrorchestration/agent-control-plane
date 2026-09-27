from __future__ import annotations

import pytest

from agent_control_plane import (
    BudgetExceeded,
    ExecutionBudget,
    TASK_BUDGET_CHECKPOINT_SCHEMA,
    Task,
    TaskState,
    checkpoint_task_budget,
    restore_task_budget_checkpoint,
    task_budget_checkpoint_sha256,
)


def test_budget_checkpoint_round_trip_preserves_identity_budget_and_usage():
    task = Task(
        payload={"resume": "caller-owned"},
        id="task-checkpoint-1",
        budget=ExecutionBudget(max_steps=5, max_tool_calls=3, max_tokens=1000, max_cost=2.5),
    )
    task.consume(steps=2, tool_calls=1, tokens=250, cost=0.75)

    checkpoint = checkpoint_task_budget(task)
    resumed = restore_task_budget_checkpoint(payload={"resume": "restored"}, checkpoint=checkpoint)

    assert checkpoint["schema"] == TASK_BUDGET_CHECKPOINT_SCHEMA
    assert resumed.id == task.id
    assert resumed.budget == task.budget
    assert resumed.usage.steps == 2
    assert resumed.usage.tool_calls == 1
    assert resumed.usage.tokens == 250
    assert resumed.usage.cost == 0.75


def test_resumed_task_enforces_only_remaining_budget():
    task = Task(payload=None, id="task-checkpoint-2", budget=ExecutionBudget(max_steps=3))
    task.consume(steps=2)
    resumed = restore_task_budget_checkpoint(payload=None, checkpoint=checkpoint_task_budget(task))

    resumed.consume(steps=1)
    assert resumed.usage.steps == 3
    with pytest.raises(BudgetExceeded):
        resumed.consume(steps=1)
    assert resumed.usage.steps == 3


def test_checkpoint_rejects_exhausted_task():
    task = Task(payload=None, id="task-exhausted", budget=ExecutionBudget(max_steps=1))
    with pytest.raises(BudgetExceeded):
        task.consume(steps=2)

    with pytest.raises(ValueError, match="budget-exhausted"):
        checkpoint_task_budget(task)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda c: c.update(schema="wrong"),
        lambda c: c.update(task_id=""),
        lambda c: c["usage"].update(steps=-1),
        lambda c: c["usage"].update(steps=6),
        lambda c: c["usage"].update(cost=float("nan")),
        lambda c: c["budget"].update(max_steps=-1),
    ],
)
def test_restore_rejects_malformed_or_impossible_checkpoint(mutator):
    task = Task(payload=None, id="task-checkpoint-3", budget=ExecutionBudget(max_steps=5, max_cost=1.0))
    task.consume(steps=1, cost=0.25)
    checkpoint = checkpoint_task_budget(task)
    mutator(checkpoint)

    with pytest.raises((TypeError, ValueError)):
        restore_task_budget_checkpoint(payload=None, checkpoint=checkpoint)


def test_restore_does_not_restore_payload_result_or_terminal_state():
    task = Task(payload={"secret": "caller-owned"}, id="task-checkpoint-4", budget=ExecutionBudget(max_steps=4))
    task.result = "not checkpointed"
    task.consume(steps=1)

    checkpoint = checkpoint_task_budget(task)
    resumed = restore_task_budget_checkpoint(payload={"fresh": True}, checkpoint=checkpoint)

    assert resumed.payload == {"fresh": True}
    assert resumed.result is None
    assert resumed.error is None
    assert resumed.state.value == "created"

def test_running_budget_checkpoint_restores_as_fresh_created_task():
    task = Task(payload=None, id="task-running", budget=ExecutionBudget(max_steps=5))
    task.state = TaskState.RUNNING
    task.consume(steps=2)

    checkpoint = checkpoint_task_budget(task)
    resumed = restore_task_budget_checkpoint(payload="resume-token", checkpoint=checkpoint)

    assert checkpoint["source_state"] == "running"
    assert resumed.state is TaskState.CREATED
    assert resumed.usage.steps == 2


@pytest.mark.parametrize("state", [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED])
def test_terminal_task_budget_checkpoint_is_rejected(state):
    task = Task(payload=None, id=f"terminal-{state.value}", budget=ExecutionBudget(max_steps=5))
    task.state = state

    with pytest.raises(ValueError, match="not checkpointable"):
        checkpoint_task_budget(task)


def test_fabricated_terminal_source_state_is_rejected_on_restore():
    task = Task(payload=None, id="task-terminal-fabrication", budget=ExecutionBudget(max_steps=5))
    checkpoint = checkpoint_task_budget(task)
    checkpoint["source_state"] = "completed"

    with pytest.raises(ValueError, match="not resumable"):
        restore_task_budget_checkpoint(payload=None, checkpoint=checkpoint)

def test_checkpoint_content_identity_is_deterministic():
    task = Task(payload=None, id="identity-1", budget=ExecutionBudget(max_steps=4))
    task.consume(steps=1)
    checkpoint = checkpoint_task_budget(task)
    reordered = dict(reversed(list(checkpoint.items())))

    assert task_budget_checkpoint_sha256(checkpoint) == task_budget_checkpoint_sha256(reordered)


def test_restore_accepts_matching_checkpoint_identity():
    task = Task(payload=None, id="identity-2", budget=ExecutionBudget(max_steps=4))
    task.consume(steps=2)
    checkpoint = checkpoint_task_budget(task)
    expected = task_budget_checkpoint_sha256(checkpoint)

    resumed = restore_task_budget_checkpoint(
        payload="resumed",
        checkpoint=checkpoint,
        expected_checkpoint_sha256=expected,
    )
    assert resumed.usage.steps == 2


def test_restore_rejects_checkpoint_changed_after_identity_binding():
    task = Task(payload=None, id="identity-3", budget=ExecutionBudget(max_steps=5))
    task.consume(steps=1)
    checkpoint = checkpoint_task_budget(task)
    expected = task_budget_checkpoint_sha256(checkpoint)
    checkpoint["usage"]["steps"] = 2

    with pytest.raises(ValueError, match="sha256 mismatch"):
        restore_task_budget_checkpoint(
            payload=None,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=expected,
        )


@pytest.mark.parametrize("value", ["", "abc", "0" * 63, "uppercase-not-allowed"])
def test_restore_rejects_malformed_expected_checkpoint_identity(value):
    task = Task(payload=None, id="identity-4")
    checkpoint = checkpoint_task_budget(task)

    with pytest.raises(ValueError, match="64 lowercase hex"):
        restore_task_budget_checkpoint(
            payload=None,
            checkpoint=checkpoint,
            expected_checkpoint_sha256=value,
        )


def test_restore_rejects_unknown_top_level_checkpoint_fields():
    task = Task(payload=None, id="extra-field")
    checkpoint = checkpoint_task_budget(task)
    checkpoint["unexpected"] = "value"

    with pytest.raises(ValueError, match="fields mismatch"):
        restore_task_budget_checkpoint(payload=None, checkpoint=checkpoint)
