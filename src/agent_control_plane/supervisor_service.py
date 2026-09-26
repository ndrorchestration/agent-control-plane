"""Typed lifecycle contract for a future long-running ACP supervisor service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .authority import AuthorityValidationError


SUPERVISOR_SERVICE_SCHEMA_VERSION = (
    "agent-control-plane.supervisor-service.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


class SupervisorServiceState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class SupervisorStopReason(str, Enum):
    OPERATOR_REQUEST = "operator_request"
    SIGNAL_TERM = "signal_term"
    SIGNAL_INT = "signal_int"
    WORKER_GIVE_UP = "worker_give_up"
    STARTUP_FAILURE = "startup_failure"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class SupervisorWorkerRegistration:
    worker_id: str
    process_id: str
    ownership_token: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "worker_id",
            _required(self.worker_id, "worker_id"),
        )
        object.__setattr__(
            self,
            "process_id",
            _required(self.process_id, "process_id"),
        )
        object.__setattr__(
            self,
            "ownership_token",
            _required(self.ownership_token, "ownership_token"),
        )


@dataclass(frozen=True)
class SupervisorServiceSnapshot:
    service_id: str
    state: SupervisorServiceState
    worker_ids: tuple[str, ...]
    stop_reason: SupervisorStopReason | None
    schema_version: str = SUPERVISOR_SERVICE_SCHEMA_VERSION


class SupervisorServiceContract:
    """Pure lifecycle state machine for future daemon/service execution."""

    def __init__(
        self,
        *,
        service_id: str,
        workers: Iterable[SupervisorWorkerRegistration],
    ) -> None:
        self.service_id = _required(service_id, "service_id")
        registrations = tuple(workers)
        if not registrations:
            raise AuthorityValidationError(
                "supervisor service requires at least one worker"
            )
        if not all(
            isinstance(worker, SupervisorWorkerRegistration)
            for worker in registrations
        ):
            raise AuthorityValidationError(
                "workers must be SupervisorWorkerRegistration"
            )

        worker_ids = [worker.worker_id for worker in registrations]
        process_ids = [worker.process_id for worker in registrations]
        ownership_tokens = [worker.ownership_token for worker in registrations]
        if len(set(worker_ids)) != len(worker_ids):
            raise AuthorityValidationError("duplicate worker_id")
        if len(set(process_ids)) != len(process_ids):
            raise AuthorityValidationError("duplicate process_id")
        if len(set(ownership_tokens)) != len(ownership_tokens):
            raise AuthorityValidationError("duplicate ownership_token")

        self._workers = registrations
        self._state = SupervisorServiceState.CREATED
        self._stop_reason: SupervisorStopReason | None = None

    @property
    def workers(self) -> tuple[SupervisorWorkerRegistration, ...]:
        return self._workers

    @property
    def state(self) -> SupervisorServiceState:
        return self._state

    def snapshot(self) -> SupervisorServiceSnapshot:
        return SupervisorServiceSnapshot(
            service_id=self.service_id,
            state=self._state,
            worker_ids=tuple(worker.worker_id for worker in self._workers),
            stop_reason=self._stop_reason,
        )

    def begin_startup(self) -> SupervisorServiceSnapshot:
        if self._state is not SupervisorServiceState.CREATED:
            raise AuthorityValidationError(
                f"cannot begin startup from {self._state.value}"
            )
        self._state = SupervisorServiceState.STARTING
        return self.snapshot()

    def mark_running(self) -> SupervisorServiceSnapshot:
        if self._state is not SupervisorServiceState.STARTING:
            raise AuthorityValidationError(
                f"cannot mark running from {self._state.value}"
            )
        self._state = SupervisorServiceState.RUNNING
        return self.snapshot()

    def request_stop(
        self,
        reason: SupervisorStopReason,
    ) -> SupervisorServiceSnapshot:
        if not isinstance(reason, SupervisorStopReason):
            raise AuthorityValidationError(
                "reason must be SupervisorStopReason"
            )
        if self._state not in (
            SupervisorServiceState.STARTING,
            SupervisorServiceState.RUNNING,
        ):
            raise AuthorityValidationError(
                f"cannot request stop from {self._state.value}"
            )
        self._state = SupervisorServiceState.STOP_REQUESTED
        self._stop_reason = reason
        return self.snapshot()

    def begin_stopping(self) -> SupervisorServiceSnapshot:
        if self._state is not SupervisorServiceState.STOP_REQUESTED:
            raise AuthorityValidationError(
                f"cannot begin stopping from {self._state.value}"
            )
        self._state = SupervisorServiceState.STOPPING
        return self.snapshot()

    def mark_stopped(self) -> SupervisorServiceSnapshot:
        if self._state is not SupervisorServiceState.STOPPING:
            raise AuthorityValidationError(
                f"cannot mark stopped from {self._state.value}"
            )
        self._state = SupervisorServiceState.STOPPED
        return self.snapshot()

    def mark_failed(
        self,
        reason: SupervisorStopReason,
    ) -> SupervisorServiceSnapshot:
        if not isinstance(reason, SupervisorStopReason):
            raise AuthorityValidationError(
                "reason must be SupervisorStopReason"
            )
        if self._state in (
            SupervisorServiceState.STOPPED,
            SupervisorServiceState.FAILED,
        ):
            raise AuthorityValidationError(
                f"cannot fail from {self._state.value}"
            )
        self._state = SupervisorServiceState.FAILED
        self._stop_reason = reason
        return self.snapshot()

    def handle_signal(self, signal_name: str) -> SupervisorServiceSnapshot:
        normalized = _required(signal_name, "signal_name").upper()
        if normalized in ("SIGTERM", "TERM"):
            reason = SupervisorStopReason.SIGNAL_TERM
        elif normalized in ("SIGINT", "INT"):
            reason = SupervisorStopReason.SIGNAL_INT
        else:
            raise AuthorityValidationError(
                f"unsupported supervisor signal: {signal_name}"
            )
        return self.request_stop(reason)
