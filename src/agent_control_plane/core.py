"""Deterministic task lifecycle and routing kernel.

This module intentionally contains no model/provider integration. It provides
an inspectable substrate that higher-level agent systems can adapt.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional
from uuid import uuid4


class TaskState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    payload: object
    id: str = field(default_factory=lambda: str(uuid4()))
    state: TaskState = TaskState.CREATED
    result: object = None
    error: Optional[str] = None


Handler = Callable[[Task], object]


class ControlPlane:
    """Small deterministic control-plane kernel.

    Routing is explicit: callers register a handler under a capability name
    and dispatch a task to that capability. Lifecycle transitions are kept
    inside the control plane so they can be tested independently of agents.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}
        self.events = []

    def register(self, capability: str, handler: Handler) -> None:
        if not capability.strip():
            raise ValueError("capability must not be empty")
        self._handlers[capability] = handler

    def dispatch(self, capability: str, task: Task) -> Task:
        if task.state is not TaskState.CREATED:
            raise ValueError(f"task {task.id} is not dispatchable from {task.state}")
        handler = self._handlers.get(capability)
        if handler is None:
            raise KeyError(f"no handler registered for capability: {capability}")

        self._record(task, "running", capability=capability)
        task.state = TaskState.RUNNING
        try:
            task.result = handler(task)
            task.state = TaskState.COMPLETED
            self._record(task, "completed", capability=capability)
        except Exception as exc:  # boundary converts execution errors to state
            task.error = f"{type(exc).__name__}: {exc}"
            task.state = TaskState.FAILED
            self._record(task, "failed", capability=capability, error=task.error)
        return task

    def cancel(self, task: Task) -> Task:
        if task.state not in (TaskState.CREATED, TaskState.RUNNING):
            raise ValueError(f"task {task.id} cannot be cancelled from {task.state}")
        task.state = TaskState.CANCELLED
        self._record(task, "cancelled")
        return task

    def _record(self, task: Task, event: str, **details: object) -> None:
        self.events.append({"task_id": task.id, "event": event, **details})
