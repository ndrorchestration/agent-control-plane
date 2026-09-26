"""Finite caller-started runner for persisted ACP process monitoring cadence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Callable

from .authority import AuthorityValidationError
from .process_monitor_cadence import (
    ScheduledProcessMonitor,
    ScheduledProcessMonitorResult,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class FiniteProcessMonitorRun:
    cycles_requested: int
    cycles_completed: int
    monitor_results: tuple[ScheduledProcessMonitorResult, ...]


class FiniteProcessMonitorRunner:
    """Run a bounded number of scheduled monitor checks, then return."""

    def __init__(
        self,
        *,
        scheduler: ScheduledProcessMonitor,
        interval_seconds: float,
        max_cycles: int,
        now_provider: Callable[[], str] = _utc_now,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(scheduler, ScheduledProcessMonitor):
            raise AuthorityValidationError(
                "scheduler must be ScheduledProcessMonitor"
            )
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or interval_seconds < 0
        ):
            raise AuthorityValidationError(
                "interval_seconds must be >= 0"
            )
        if (
            isinstance(max_cycles, bool)
            or not isinstance(max_cycles, int)
            or max_cycles < 1
        ):
            raise AuthorityValidationError(
                "max_cycles must be an integer >= 1"
            )
        if not callable(now_provider):
            raise AuthorityValidationError(
                "now_provider must be callable"
            )
        if not callable(sleep_fn):
            raise AuthorityValidationError("sleep_fn must be callable")

        self.scheduler = scheduler
        self.interval_seconds = float(interval_seconds)
        self.max_cycles = max_cycles
        self.now_provider = now_provider
        self.sleep_fn = sleep_fn

    def run(self) -> FiniteProcessMonitorRun:
        results: list[ScheduledProcessMonitorResult] = []
        for index in range(self.max_cycles):
            now = self.now_provider()
            results.append(
                self.scheduler.run_if_due(now=now)
            )
            if index + 1 < self.max_cycles:
                self.sleep_fn(self.interval_seconds)

        return FiniteProcessMonitorRun(
            cycles_requested=self.max_cycles,
            cycles_completed=len(results),
            monitor_results=tuple(results),
        )
