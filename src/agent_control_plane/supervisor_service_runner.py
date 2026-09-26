"""Bounded multi-worker supervisor service runner for ACP."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Optional

from .authority import AuthorityValidationError
from .process_monitor_cadence import (
    ScheduledProcessMonitor,
    ScheduledProcessMonitorResult,
)
from .process_runtime import ManagedProcessController, ProcessObservation
from .process_supervision import ProcessSupervisionDecision
from .supervisor_service import (
    SupervisorServiceContract,
    SupervisorServiceSnapshot,
    SupervisorServiceState,
    SupervisorStopReason,
    SupervisorWorkerRegistration,
)


@dataclass(frozen=True)
class SupervisorWorkerRuntime:
    registration: SupervisorWorkerRegistration
    controller: ManagedProcessController
    scheduler: ScheduledProcessMonitor

    def __post_init__(self) -> None:
        if not isinstance(self.registration, SupervisorWorkerRegistration):
            raise AuthorityValidationError(
                "registration must be SupervisorWorkerRegistration"
            )
        if not isinstance(self.controller, ManagedProcessController):
            raise AuthorityValidationError(
                "controller must be ManagedProcessController"
            )
        if not isinstance(self.scheduler, ScheduledProcessMonitor):
            raise AuthorityValidationError(
                "scheduler must be ScheduledProcessMonitor"
            )
        if self.controller.spec.process_id != self.registration.process_id:
            raise AuthorityValidationError(
                "worker registration process_id mismatch"
            )
        if self.scheduler.monitor_tick.controller is not self.controller:
            raise AuthorityValidationError(
                "scheduler must monitor the registered controller"
            )


@dataclass(frozen=True)
class SupervisorCycleRecord:
    cycle_index: int
    worker_results: tuple[
        tuple[str, ScheduledProcessMonitorResult], ...
    ]


@dataclass(frozen=True)
class BoundedSupervisorServiceReport:
    final_snapshot: SupervisorServiceSnapshot
    cycles_completed: int
    cycle_records: tuple[SupervisorCycleRecord, ...]
    final_observations: tuple[ProcessObservation, ...]


class BoundedSupervisorServiceRunner:
    """Run a finite supervisor-service lifecycle over one or more workers."""

    def __init__(
        self,
        *,
        contract: SupervisorServiceContract,
        workers: tuple[SupervisorWorkerRuntime, ...],
        max_cycles: int,
        interval_seconds: float,
        now_provider: Callable[[], str],
        sleep_fn: Callable[[float], None] = time.sleep,
        signal_provider: Optional[Callable[[int], Optional[str]]] = None,
        terminate_timeout_seconds: float = 5.0,
    ) -> None:
        if not isinstance(contract, SupervisorServiceContract):
            raise AuthorityValidationError(
                "contract must be SupervisorServiceContract"
            )
        if (
            not isinstance(workers, tuple)
            or not workers
            or not all(
                isinstance(worker, SupervisorWorkerRuntime)
                for worker in workers
            )
        ):
            raise AuthorityValidationError(
                "workers must be a non-empty tuple of SupervisorWorkerRuntime"
            )
        if (
            isinstance(max_cycles, bool)
            or not isinstance(max_cycles, int)
            or max_cycles < 1
        ):
            raise AuthorityValidationError(
                "max_cycles must be an integer >= 1"
            )
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or interval_seconds < 0
        ):
            raise AuthorityValidationError(
                "interval_seconds must be >= 0"
            )
        if not callable(now_provider):
            raise AuthorityValidationError(
                "now_provider must be callable"
            )
        if not callable(sleep_fn):
            raise AuthorityValidationError("sleep_fn must be callable")
        if signal_provider is not None and not callable(signal_provider):
            raise AuthorityValidationError(
                "signal_provider must be callable or None"
            )
        if terminate_timeout_seconds <= 0:
            raise AuthorityValidationError(
                "terminate_timeout_seconds must be > 0"
            )

        contract_worker_ids = tuple(
            registration.worker_id for registration in contract.workers
        )
        runtime_worker_ids = tuple(
            worker.registration.worker_id for worker in workers
        )
        if runtime_worker_ids != contract_worker_ids:
            raise AuthorityValidationError(
                "worker runtime order must exactly match service contract"
            )

        self.contract = contract
        self.workers = workers
        self.max_cycles = max_cycles
        self.interval_seconds = float(interval_seconds)
        self.now_provider = now_provider
        self.sleep_fn = sleep_fn
        self.signal_provider = signal_provider
        self.terminate_timeout_seconds = terminate_timeout_seconds

    def _terminate_all(self) -> tuple[ProcessObservation, ...]:
        observations: list[ProcessObservation] = []
        for worker in reversed(self.workers):
            observations.append(
                worker.controller.terminate(
                    timeout_seconds=self.terminate_timeout_seconds
                )
            )
        observations.reverse()
        return tuple(observations)

    def run(self) -> BoundedSupervisorServiceReport:
        cycle_records: list[SupervisorCycleRecord] = []

        self.contract.begin_startup()
        try:
            for worker in self.workers:
                observation = worker.controller.observe()
                if not observation.running:
                    worker.controller.start()
        except Exception:
            self.contract.mark_failed(
                SupervisorStopReason.STARTUP_FAILURE
            )
            final_observations = self._terminate_all()
            return BoundedSupervisorServiceReport(
                final_snapshot=self.contract.snapshot(),
                cycles_completed=0,
                cycle_records=(),
                final_observations=final_observations,
            )

        self.contract.mark_running()

        for cycle_index in range(self.max_cycles):
            if self.contract.state is not SupervisorServiceState.RUNNING:
                break

            if self.signal_provider is not None:
                signal_name = self.signal_provider(cycle_index)
                if signal_name is not None:
                    self.contract.handle_signal(signal_name)
                    break

            worker_results: list[
                tuple[str, ScheduledProcessMonitorResult]
            ] = []
            now = self.now_provider()
            for worker in self.workers:
                if self.contract.state is not SupervisorServiceState.RUNNING:
                    break
                result = worker.scheduler.run_if_due(
                    now=now,
                    timeout_seconds=self.terminate_timeout_seconds,
                )
                worker_results.append(
                    (worker.registration.worker_id, result)
                )
                if (
                    result.tick_result is not None
                    and result.tick_result.decision
                    is ProcessSupervisionDecision.GIVE_UP
                ):
                    self.contract.request_stop(
                        SupervisorStopReason.WORKER_GIVE_UP
                    )
                    break

            cycle_records.append(
                SupervisorCycleRecord(
                    cycle_index=cycle_index,
                    worker_results=tuple(worker_results),
                )
            )

            if self.contract.state is not SupervisorServiceState.RUNNING:
                break
            if cycle_index + 1 < self.max_cycles:
                self.sleep_fn(self.interval_seconds)

        if self.contract.state is SupervisorServiceState.RUNNING:
            self.contract.request_stop(
                SupervisorStopReason.OPERATOR_REQUEST
            )

        if self.contract.state is SupervisorServiceState.STOP_REQUESTED:
            self.contract.begin_stopping()

        final_observations = self._terminate_all()

        if self.contract.state is SupervisorServiceState.STOPPING:
            self.contract.mark_stopped()

        return BoundedSupervisorServiceReport(
            final_snapshot=self.contract.snapshot(),
            cycles_completed=len(cycle_records),
            cycle_records=tuple(cycle_records),
            final_observations=final_observations,
        )
