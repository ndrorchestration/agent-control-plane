"""Characterization-only context efficiency telemetry.

The metrics in this module observe declared counts. They do not decide routing,
authorize execution, suppress context, or claim semantic relevance.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Optional


def _count(name: str, value: Optional[int]) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None")


def _ratio(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class ContextTelemetry:
    """Observed counts for one bounded agent/model task."""

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    tool_result_tokens: Optional[int] = None
    tool_definitions_exposed: Optional[int] = None
    tools_invoked: Optional[int] = None
    retrieved_tokens: Optional[int] = None
    used_retrieved_tokens: Optional[int] = None
    retrieved_items: Optional[int] = None
    cacheable_prefix_tokens: Optional[int] = None
    novel_prefix_tokens: Optional[int] = None
    decision_relevant_input_tokens: Optional[int] = None

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            _count(name, value)
        if (
            self.tools_invoked is not None
            and self.tool_definitions_exposed is not None
            and self.tools_invoked > self.tool_definitions_exposed
        ):
            raise ValueError("tools_invoked cannot exceed tool_definitions_exposed")
        if (
            self.used_retrieved_tokens is not None
            and self.retrieved_tokens is not None
            and self.used_retrieved_tokens > self.retrieved_tokens
        ):
            raise ValueError("used_retrieved_tokens cannot exceed retrieved_tokens")
        if (
            self.decision_relevant_input_tokens is not None
            and self.input_tokens is not None
            and self.decision_relevant_input_tokens > self.input_tokens
        ):
            raise ValueError(
                "decision_relevant_input_tokens cannot exceed input_tokens"
            )
        if (
            self.cacheable_prefix_tokens is not None
            and self.novel_prefix_tokens is not None
            and self.input_tokens is not None
            and self.cacheable_prefix_tokens + self.novel_prefix_tokens
            > self.input_tokens
        ):
            raise ValueError("prefix token counts cannot exceed input_tokens")

    @property
    def context_efficiency(self) -> Optional[float]:
        return _ratio(self.decision_relevant_input_tokens, self.input_tokens)

    @property
    def retrieval_yield(self) -> Optional[float]:
        return _ratio(self.used_retrieved_tokens, self.retrieved_tokens)

    @property
    def tool_utilization(self) -> Optional[float]:
        return _ratio(self.tools_invoked, self.tool_definitions_exposed)

    @property
    def context_churn(self) -> Optional[float]:
        if self.novel_prefix_tokens is None:
            return None
        if self.cacheable_prefix_tokens is None:
            return None
        total = self.novel_prefix_tokens + self.cacheable_prefix_tokens
        return None if total == 0 else self.novel_prefix_tokens / total

    def to_mapping(self) -> dict[str, int | float | None]:
        return {
            **self.__dict__,
            "context_efficiency": self.context_efficiency,
            "retrieval_yield": self.retrieval_yield,
            "tool_utilization": self.tool_utilization,
            "context_churn": self.context_churn,
        }
