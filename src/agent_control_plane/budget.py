"""Deterministic cooperative execution-budget primitives."""

from dataclasses import dataclass
from math import isfinite
from typing import Optional


class BudgetExceeded(RuntimeError):
    """Raised when a task attempts to consume beyond its declared budget."""

    def __init__(self, resource: str, limit: float, attempted: float) -> None:
        self.resource = resource
        self.limit = limit
        self.attempted = attempted
        super().__init__(f"{resource} budget exceeded: attempted {attempted}, limit {limit}")


def _validate_count(name: str, value: Optional[int]) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None")


def _validate_cost(name: str, value: Optional[float]) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a non-negative finite number or None")
    if not isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be a non-negative finite number or None")


@dataclass(frozen=True)
class ExecutionBudget:
    """Declared deterministic resource ceilings for one task."""

    max_steps: Optional[int] = None
    max_tool_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    max_cost: Optional[float] = None

    def __post_init__(self) -> None:
        _validate_count("max_steps", self.max_steps)
        _validate_count("max_tool_calls", self.max_tool_calls)
        _validate_count("max_tokens", self.max_tokens)
        _validate_cost("max_cost", self.max_cost)


@dataclass
class BudgetUsage:
    """Accumulated task usage, updated atomically after budget checks."""

    steps: int = 0
    tool_calls: int = 0
    tokens: int = 0
    cost: float = 0.0

    def consume(
        self,
        budget: Optional[ExecutionBudget],
        *,
        steps: int = 0,
        tool_calls: int = 0,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        _validate_count("steps", steps)
        _validate_count("tool_calls", tool_calls)
        _validate_count("tokens", tokens)
        _validate_cost("cost", cost)

        proposed = {
            "steps": self.steps + steps,
            "tool_calls": self.tool_calls + tool_calls,
            "tokens": self.tokens + tokens,
            "cost": self.cost + float(cost),
        }
        if budget is not None:
            limits = {
                "steps": budget.max_steps,
                "tool_calls": budget.max_tool_calls,
                "tokens": budget.max_tokens,
                "cost": budget.max_cost,
            }
            for resource, attempted in proposed.items():
                limit = limits[resource]
                if limit is not None and attempted > limit:
                    raise BudgetExceeded(resource, float(limit), float(attempted))

        self.steps = int(proposed["steps"])
        self.tool_calls = int(proposed["tool_calls"])
        self.tokens = int(proposed["tokens"])
        self.cost = float(proposed["cost"])

    def summary(self) -> str:
        return (
            f"steps={self.steps};tool_calls={self.tool_calls};"
            f"tokens={self.tokens};cost={self.cost:.6f}"
        )
