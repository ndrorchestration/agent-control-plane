"""Deterministic process-supervision policy for ACP relay workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from .authority import AuthorityValidationError


def _utc(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AuthorityValidationError(
            f"{field_name} must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(
            f"{field_name} must be timezone-aware UTC"
        )
    if parsed.utcoffset() != timedelta(0):
        raise AuthorityValidationError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc)


class ProcessSupervisionDecision(str, Enum):
    RESTART = "restart"
    HOLD = "hold"
    GIVE_UP = "give_up"


@dataclass(frozen=True)
class ProcessFailureState:
    process_id: str
    failure_count: int
    last_failure_at: str
    last_restart_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.process_id, str) or not self.process_id.strip():
            raise AuthorityValidationError("process_id must not be blank")
        if (
            isinstance(self.failure_count, bool)
            or not isinstance(self.failure_count, int)
            or self.failure_count < 1
        ):
            raise AuthorityValidationError(
                "failure_count must be an integer >= 1"
            )
        _utc(self.last_failure_at, "last_failure_at")
        if self.last_restart_at is not None:
            _utc(self.last_restart_at, "last_restart_at")


@dataclass(frozen=True)
class ProcessSupervisionPolicy:
    max_restarts: int = 3
    min_restart_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_restarts, bool)
            or not isinstance(self.max_restarts, int)
            or self.max_restarts < 0
        ):
            raise AuthorityValidationError(
                "max_restarts must be an integer >= 0"
            )
        if (
            isinstance(self.min_restart_interval_seconds, bool)
            or not isinstance(self.min_restart_interval_seconds, (int, float))
            or self.min_restart_interval_seconds < 0
        ):
            raise AuthorityValidationError(
                "min_restart_interval_seconds must be >= 0"
            )

    def decide(
        self,
        state: ProcessFailureState,
        *,
        now: str,
    ) -> ProcessSupervisionDecision:
        current = _utc(now, "now")
        if state.failure_count > self.max_restarts:
            return ProcessSupervisionDecision.GIVE_UP

        if state.last_restart_at is not None:
            restart_at = _utc(state.last_restart_at, "last_restart_at")
            elapsed = (current - restart_at).total_seconds()
            if elapsed < self.min_restart_interval_seconds:
                return ProcessSupervisionDecision.HOLD

        return ProcessSupervisionDecision.RESTART
