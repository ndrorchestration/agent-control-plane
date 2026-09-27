"""Bounded task-budget checkpoint and resume primitives."""

from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping

from .budget import BudgetUsage, ExecutionBudget
from .core import Task, TaskState

TASK_BUDGET_CHECKPOINT_SCHEMA = "agent-control-plane.task-budget-checkpoint.v0-candidate"
_CHECKPOINTABLE_STATES = frozenset({TaskState.CREATED.value, TaskState.RUNNING.value})


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _non_negative_cost(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a non-negative finite number")
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
    return numeric


def _budget_to_mapping(budget: ExecutionBudget | None) -> dict[str, Any] | None:
    if budget is None:
        return None
    return {
        "max_steps": budget.max_steps,
        "max_tool_calls": budget.max_tool_calls,
        "max_tokens": budget.max_tokens,
        "max_cost": budget.max_cost,
    }


def _usage_to_mapping(usage: BudgetUsage) -> dict[str, Any]:
    return {
        "steps": usage.steps,
        "tool_calls": usage.tool_calls,
        "tokens": usage.tokens,
        "cost": usage.cost,
    }


def checkpoint_task_budget(task: Task) -> dict[str, Any]:
    """Serialize only task identity, budget ceilings, and consumed usage."""
    if not isinstance(task, Task):
        raise TypeError("task must be Task")
    if task.budget_exhausted:
        raise ValueError("budget-exhausted task cannot be checkpointed")
    if task.state.value not in _CHECKPOINTABLE_STATES:
        raise ValueError(f"task state is not checkpointable: {task.state.value}")
    return {
        "schema": TASK_BUDGET_CHECKPOINT_SCHEMA,
        "task_id": task.id,
        "source_state": task.state.value,
        "budget": _budget_to_mapping(task.budget),
        "usage": _usage_to_mapping(task.usage),
    }


def canonical_task_budget_checkpoint_bytes(checkpoint: Mapping[str, Any]) -> bytes:
    """Return deterministic checkpoint bytes; this is identity, not authentication."""
    if not isinstance(checkpoint, Mapping):
        raise TypeError("checkpoint must be a mapping")
    try:
        return json.dumps(
            dict(checkpoint),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("checkpoint is not canonically serializable") from exc


def task_budget_checkpoint_sha256(checkpoint: Mapping[str, Any]) -> str:
    """Return deterministic SHA-256 content identity for a checkpoint."""
    return hashlib.sha256(canonical_task_budget_checkpoint_bytes(checkpoint)).hexdigest()


def _validate_expected_sha256(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(
            "expected checkpoint sha256 must be 64 lowercase hex characters"
        )
    return value


def _parse_budget(value: Any) -> ExecutionBudget | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("checkpoint budget must be a mapping or null")
    expected = {"max_steps", "max_tool_calls", "max_tokens", "max_cost"}
    if set(value) != expected:
        raise ValueError("checkpoint budget fields mismatch")
    return ExecutionBudget(
        max_steps=value["max_steps"],
        max_tool_calls=value["max_tool_calls"],
        max_tokens=value["max_tokens"],
        max_cost=value["max_cost"],
    )


def _parse_usage(value: Any) -> BudgetUsage:
    if not isinstance(value, Mapping):
        raise TypeError("checkpoint usage must be a mapping")
    expected = {"steps", "tool_calls", "tokens", "cost"}
    if set(value) != expected:
        raise ValueError("checkpoint usage fields mismatch")
    return BudgetUsage(
        steps=_non_negative_int(value["steps"], "usage.steps"),
        tool_calls=_non_negative_int(value["tool_calls"], "usage.tool_calls"),
        tokens=_non_negative_int(value["tokens"], "usage.tokens"),
        cost=_non_negative_cost(value["cost"], "usage.cost"),
    )


def _assert_usage_within_budget(
    usage: BudgetUsage,
    budget: ExecutionBudget | None,
) -> None:
    if budget is None:
        return
    pairs = (
        ("steps", usage.steps, budget.max_steps),
        ("tool_calls", usage.tool_calls, budget.max_tool_calls),
        ("tokens", usage.tokens, budget.max_tokens),
        ("cost", usage.cost, budget.max_cost),
    )
    for resource, consumed, limit in pairs:
        if limit is not None and consumed > limit:
            raise ValueError(
                f"checkpoint usage exceeds {resource} budget: {consumed} > {limit}"
            )


def restore_task_budget_checkpoint(
    *,
    payload: object,
    checkpoint: Mapping[str, Any],
    expected_checkpoint_sha256: str | None = None,
) -> Task:
    """Create a fresh task that preserves prior resource consumption."""
    if not isinstance(checkpoint, Mapping):
        raise TypeError("checkpoint must be a mapping")
    expected_fields = {"schema", "task_id", "source_state", "budget", "usage"}
    if set(checkpoint) != expected_fields:
        raise ValueError("checkpoint fields mismatch")
    if expected_checkpoint_sha256 is not None:
        expected = _validate_expected_sha256(expected_checkpoint_sha256)
        if task_budget_checkpoint_sha256(checkpoint) != expected:
            raise ValueError("task-budget checkpoint sha256 mismatch")
    if checkpoint.get("schema") != TASK_BUDGET_CHECKPOINT_SCHEMA:
        raise ValueError("unsupported task-budget checkpoint schema")
    task_id = checkpoint.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("checkpoint task_id must be non-empty")
    source_state = checkpoint.get("source_state")
    if source_state not in _CHECKPOINTABLE_STATES:
        raise ValueError("checkpoint source state is not resumable")

    budget = _parse_budget(checkpoint.get("budget"))
    usage = _parse_usage(checkpoint.get("usage"))
    _assert_usage_within_budget(usage, budget)

    return Task(payload=payload, id=task_id, budget=budget, usage=usage)
