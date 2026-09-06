"""Deterministic task lifecycle, routing, policy, and run-scoped provenance kernel."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional
from uuid import uuid4

from .policy import Policy, evaluate_policy
from .provenance import ProvenanceEvent, event_now


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
    """Small deterministic control-plane kernel with policy and provenance."""

    def __init__(self, policy: Optional[Policy] = None, run_id: Optional[str] = None) -> None:
        self._handlers: Dict[str, Handler] = {}
        self._policy = policy
        self.run_id = run_id or str(uuid4())
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        self.events: list[ProvenanceEvent] = []

    def register(self, capability: str, handler: Handler) -> None:
        capability = capability.strip()
        if not capability:
            raise ValueError("capability must not be empty")
        if capability in self._handlers:
            raise ValueError(f"capability already registered: {capability}")
        self._handlers[capability] = handler

    def dispatch(self, capability: str, task: Task) -> Task:
        if task.state is not TaskState.CREATED:
            raise ValueError(f"task {task.id} is not dispatchable from {task.state}")
        handler = self._handlers.get(capability)
        if handler is None:
            self._record("task.rejected", task, capability=capability, detail="unknown capability")
            raise KeyError(f"no handler registered for capability: {capability}")

        if self._policy is not None:
            decision = evaluate_policy(self._policy, capability, task)
            if not decision.allowed:
                task.error = decision.reason or "policy denied"
                self._record("task.denied", task, capability=capability, detail=task.error)
                return task

        task.state = TaskState.RUNNING
        self._record("task.started", task, capability=capability, state=task.state.value)
        try:
            task.result = handler(task)
            task.state = TaskState.COMPLETED
            self._record("task.completed", task, capability=capability, state=task.state.value)
        except Exception as exc:
            task.error = f"{type(exc).__name__}: {exc}"
            task.state = TaskState.FAILED
            self._record("task.failed", task, capability=capability, state=task.state.value, detail=task.error)
        return task

    def cancel(self, task: Task) -> Task:
        if task.state not in (TaskState.CREATED, TaskState.RUNNING):
            raise ValueError(f"task {task.id} cannot be cancelled from {task.state}")
        task.state = TaskState.CANCELLED
        self._record("task.cancelled", task, state=task.state.value)
        return task

    def provenance_manifest(self) -> dict[str, object]:
        """Return a portable run record without claiming durable persistence."""
        return {
            "schema": "agent-control-plane.provenance.v1",
            "run_id": self.run_id,
            "event_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
        }

    def _record(self, event: str, task: Task, **details: str) -> None:
        self.events.append(event_now(event, task.id, self.run_id, **details))
