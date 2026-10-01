"""Thin adapters demonstrating Action Admission reuse across request shapes.

These adapters translate external request records into the framework-neutral
ActionIntent. They do not evaluate authority themselves and do not execute the
requested action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .action_admission import ActionIntent
from .remote_mutation_admission import RemoteMutationIntent


@dataclass(frozen=True)
class ToolCallRequest:
    request_id: str
    actor_id: str
    tool_name: str
    action: str
    target_id: str
    target_type: str
    side_effect_class: Optional[str] = None
    context_id: Optional[str] = None


def remote_mutation_to_action_intent(intent: RemoteMutationIntent) -> ActionIntent:
    """Translate ACP's remote-mutation request shape without changing semantics."""
    if not isinstance(intent, RemoteMutationIntent):
        raise TypeError("intent must be RemoteMutationIntent")
    return ActionIntent(
        intent_id=intent.request_id,
        principal_id=intent.principal_id,
        capability=intent.capability,
        resource_id=intent.resource_id,
        resource_type=intent.resource_type,
        operation=intent.operation_id,
        side_effect_class=intent.expected_side_effect_class,
        context_id=intent.device_id,
    )


def tool_call_to_action_intent(request: ToolCallRequest) -> ActionIntent:
    """Translate a generic tool-call request into the shared ActionIntent contract."""
    if not isinstance(request, ToolCallRequest):
        raise TypeError("request must be ToolCallRequest")
    return ActionIntent(
        intent_id=request.request_id,
        principal_id=request.actor_id,
        capability=f"tool.{request.tool_name}",
        resource_id=request.target_id,
        resource_type=request.target_type,
        operation=request.action,
        side_effect_class=request.side_effect_class,
        context_id=request.context_id,
    )
