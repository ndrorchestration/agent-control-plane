"""Policy hooks for the Agent Control Plane."""

from dataclasses import dataclass
from typing import Callable, Optional

from .core import Task


Policy = Callable[[str, Task], Optional[str]]


@dataclass
class PolicyDecision:
    allowed: bool
    reason: Optional[str] = None


def evaluate_policy(policy: Policy, capability: str, task: Task) -> PolicyDecision:
    reason = policy(capability, task)
    return PolicyDecision(allowed=reason is None, reason=reason)
