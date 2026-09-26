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
from .supervisor_ownership import (
    SupervisorOwnershipLease,
    SupervisorOwnershipLeaseStore,
)
from .supervisor_runtime_checkpoint import (
    DurableSupervisorRuntimeCheckpointStore,
    SupervisorRecoveryAssessment,
    SupervisorRuntimeCheckpoint,
)
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
class SupervisorLeaseConfiguration:
    store: SupervisorOwnershipLeaseStore
    owner_id: str
    instance_token: str
    ttl_seconds: float
    service_resource_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.store, SupervisorOwnershipLeaseStore):
            raise AuthorityValidationError(
                "store must be SupervisorOwnershipLeaseStore"
            )
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise AuthorityValidationError("owner_id must not be blank")
        if (
            not isinstance(self.instance_token, str)
            or not self.instance_token.strip()
        ):
            raise AuthorityValidationError(
                "instance_token must not be blank"
            )
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, (int, float))
            or self.ttl_seconds <= 0
        ):
            raise AuthorityValidationError("ttl_seconds must be > 0")
        if (
            self.service_resource_id is not None
            and (
                not isinstance(self.service_resource_id, str)
                or not self.service_resource_id.strip()
            )
        ):
            raise AuthorityValidationError(
                "service_resource_id must be non-blank or None"
            )


@dataclass(frozen=True)
class SupervisorRuntimeCheckpointConfiguration:
    store: DurableSupervisorRuntimeCheckpointStore

    def __post_init__(self) -> None:
        if not isinstance(
            self.store,
            DurableSupervisorRuntimeCheckpointStore,
        ):
            raise AuthorityValidationError(
                "store must be DurableSupervisorRuntimeCheckpointStore"
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
    lease_fencing_tokens: tuple[tuple[str, int], ...] = ()
    service_lease_fencing_token: Optional[int] = None
    runtime_generation: Optional[int] = None
    runtime_recovery: Optional[SupervisorRecoveryAssessment] = None


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
        lease_configuration: Optional[SupervisorLeaseConfiguration] = None,
        runtime_checkpoint_configuration: Optional[
            SupervisorRuntimeCheckpointConfiguration
        ] = None,
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
        if (
            lease_configuration is not None
            and not isinstance(
                lease_configuration,
                SupervisorLeaseConfiguration,
            )
        ):
            raise AuthorityValidationError(
                "lease_configuration must be SupervisorLeaseConfiguration or None"
            )
        if (
            runtime_checkpoint_configuration is not None
            and not isinstance(
                runtime_checkpoint_configuration,
                SupervisorRuntimeCheckpointConfiguration,
            )
        ):
            raise AuthorityValidationError(
                "runtime_checkpoint_configuration must be "
                "SupervisorRuntimeCheckpointConfiguration or None"
            )
        if (
            runtime_checkpoint_configuration is not None
            and lease_configuration is None
        ):
            raise AuthorityValidationError(
                "runtime checkpoint persistence requires lease configuration"
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
        self.lease_configuration = lease_configuration
        self.runtime_checkpoint_configuration = (
            runtime_checkpoint_configuration
        )

    def _service_resource_id(self) -> str:
        assert self.lease_configuration is not None
        return (
            self.lease_configuration.service_resource_id
            or f"service:{self.contract.service_id}"
        )

    def _service_lease_token(self) -> str:
        assert self.lease_configuration is not None
        return f"{self.lease_configuration.instance_token}:service"

    def _lease_token_for(
        self,
        worker: SupervisorWorkerRuntime,
    ) -> str:
        assert self.lease_configuration is not None
        return (
            f"{self.lease_configuration.instance_token}:"
            f"{worker.registration.ownership_token}"
        )

    def _acquire_leases(
        self,
        *,
        now: str,
    ) -> dict[str, SupervisorOwnershipLease]:
        if self.lease_configuration is None:
            return {}
        acquired: dict[str, SupervisorOwnershipLease] = {}
        try:
            service_resource = self._service_resource_id()
            acquired[service_resource] = (
                self.lease_configuration.store.acquire(
                    resource_id=service_resource,
                    owner_id=self.lease_configuration.owner_id,
                    ownership_token=self._service_lease_token(),
                    now=now,
                    ttl_seconds=self.lease_configuration.ttl_seconds,
                )
            )
            for worker in self.workers:
                resource_id = worker.registration.process_id
                acquired[resource_id] = (
                    self.lease_configuration.store.acquire(
                        resource_id=resource_id,
                        owner_id=self.lease_configuration.owner_id,
                        ownership_token=self._lease_token_for(worker),
                        now=now,
                        ttl_seconds=self.lease_configuration.ttl_seconds,
                    )
                )
        except Exception:
            for lease in acquired.values():
                try:
                    self.lease_configuration.store.release(
                        lease,
                        released_at=now,
                    )
                except Exception:
                    pass
            raise
        return acquired

    def _renew_leases(
        self,
        leases: dict[str, SupervisorOwnershipLease],
        *,
        now: str,
    ) -> dict[str, SupervisorOwnershipLease]:
        if self.lease_configuration is None:
            return leases
        renewed: dict[str, SupervisorOwnershipLease] = {}
        for resource_id, lease in leases.items():
            self.lease_configuration.store.assert_current(
                lease,
                now=now,
            )
            renewed[resource_id] = (
                self.lease_configuration.store.renew(
                    lease,
                    now=now,
                    ttl_seconds=self.lease_configuration.ttl_seconds,
                )
            )
        return renewed

    def _release_leases(
        self,
        leases: dict[str, SupervisorOwnershipLease],
        *,
        now: str,
    ) -> None:
        if self.lease_configuration is None:
            return
        for lease in leases.values():
            self.lease_configuration.store.release(
                lease,
                released_at=now,
            )

    def _worker_lease_fencing_tokens(
        self,
        leases: dict[str, SupervisorOwnershipLease],
    ) -> tuple[tuple[str, int], ...]:
        service_resource = (
            self._service_resource_id()
            if self.lease_configuration is not None
            else None
        )
        return tuple(
            (resource_id, lease.fencing_token)
            for resource_id, lease in leases.items()
            if resource_id != service_resource
        )

    def _service_lease(
        self,
        leases: dict[str, SupervisorOwnershipLease],
    ) -> Optional[SupervisorOwnershipLease]:
        if self.lease_configuration is None:
            return None
        return leases.get(self._service_resource_id())

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
        leases: dict[str, SupervisorOwnershipLease] = {}
        runtime_checkpoint: Optional[SupervisorRuntimeCheckpoint] = None
        runtime_recovery: Optional[SupervisorRecoveryAssessment] = None

        def report(
            final_observations: tuple[ProcessObservation, ...],
        ) -> BoundedSupervisorServiceReport:
            service_lease = self._service_lease(leases)
            return BoundedSupervisorServiceReport(
                final_snapshot=self.contract.snapshot(),
                cycles_completed=len(cycle_records),
                cycle_records=tuple(cycle_records),
                final_observations=final_observations,
                lease_fencing_tokens=self._worker_lease_fencing_tokens(
                    leases
                ),
                service_lease_fencing_token=(
                    None
                    if service_lease is None
                    else service_lease.fencing_token
                ),
                runtime_generation=(
                    None
                    if runtime_checkpoint is None
                    else runtime_checkpoint.generation
                ),
                runtime_recovery=runtime_recovery,
            )

        def persist_snapshot(
            snapshot: SupervisorServiceSnapshot,
            *,
            updated_at: str,
        ) -> bool:
            nonlocal runtime_checkpoint
            if self.runtime_checkpoint_configuration is None:
                return True
            if runtime_checkpoint is None:
                return False
            try:
                runtime_checkpoint = (
                    self.runtime_checkpoint_configuration.store.write_snapshot(
                        runtime_checkpoint,
                        snapshot,
                        updated_at=updated_at,
                    )
                )
                return True
            except Exception:
                return False

        self.contract.begin_startup()
        try:
            startup_now = (
                self.now_provider()
                if self.lease_configuration is not None
                else None
            )
            if self.lease_configuration is not None:
                assert startup_now is not None
                leases = self._acquire_leases(now=startup_now)

            if self.runtime_checkpoint_configuration is not None:
                assert self.lease_configuration is not None
                assert startup_now is not None
                service_lease = self._service_lease(leases)
                if service_lease is None:
                    raise AuthorityValidationError(
                        "service ownership lease missing"
                    )
                started = (
                    self.runtime_checkpoint_configuration.store.begin_run(
                        service_id=self.contract.service_id,
                        owner_id=self.lease_configuration.owner_id,
                        fencing_token=service_lease.fencing_token,
                        started_at=startup_now,
                    )
                )
                runtime_checkpoint = started.checkpoint
                runtime_recovery = started.recovery

            for worker in self.workers:
                observation = worker.controller.observe()
                if not observation.running:
                    worker.controller.start()

            running_snapshot = self.contract.mark_running()
            if self.runtime_checkpoint_configuration is not None:
                if not persist_snapshot(
                    running_snapshot,
                    updated_at=self.now_provider(),
                ):
                    raise AuthorityValidationError(
                        "failed to persist RUNNING supervisor checkpoint"
                    )
        except Exception:
            if self.contract.state is not SupervisorServiceState.FAILED:
                try:
                    failed_snapshot = self.contract.mark_failed(
                        SupervisorStopReason.STARTUP_FAILURE
                    )
                    if runtime_checkpoint is not None:
                        persist_snapshot(
                            failed_snapshot,
                            updated_at=self.now_provider(),
                        )
                except Exception:
                    pass
            final_observations = self._terminate_all()
            if self.lease_configuration is not None and leases:
                try:
                    self._release_leases(
                        leases,
                        now=self.now_provider(),
                    )
                except Exception:
                    pass
            return report(final_observations)

        for cycle_index in range(self.max_cycles):
            if self.contract.state is not SupervisorServiceState.RUNNING:
                break

            if self.signal_provider is not None:
                signal_name = self.signal_provider(cycle_index)
                if signal_name is not None:
                    stop_snapshot = self.contract.handle_signal(signal_name)
                    if self.runtime_checkpoint_configuration is not None:
                        if not persist_snapshot(
                            stop_snapshot,
                            updated_at=self.now_provider(),
                        ):
                            self.contract.mark_failed(
                                SupervisorStopReason.INTERNAL_ERROR
                            )
                    break

            worker_results: list[
                tuple[str, ScheduledProcessMonitorResult]
            ] = []
            now = self.now_provider()
            if self.lease_configuration is not None:
                try:
                    leases = self._renew_leases(
                        leases,
                        now=now,
                    )
                except Exception:
                    stop_snapshot = self.contract.request_stop(
                        SupervisorStopReason.INTERNAL_ERROR
                    )
                    if self.runtime_checkpoint_configuration is not None:
                        persist_snapshot(
                            stop_snapshot,
                            updated_at=now,
                        )
                    break

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
                    stop_snapshot = self.contract.request_stop(
                        SupervisorStopReason.WORKER_GIVE_UP
                    )
                    if self.runtime_checkpoint_configuration is not None:
                        persist_snapshot(
                            stop_snapshot,
                            updated_at=now,
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
            stop_snapshot = self.contract.request_stop(
                SupervisorStopReason.OPERATOR_REQUEST
            )
            if self.runtime_checkpoint_configuration is not None:
                if not persist_snapshot(
                    stop_snapshot,
                    updated_at=self.now_provider(),
                ):
                    self.contract.mark_failed(
                        SupervisorStopReason.INTERNAL_ERROR
                    )

        if self.contract.state is SupervisorServiceState.STOP_REQUESTED:
            stopping_snapshot = self.contract.begin_stopping()
            if self.runtime_checkpoint_configuration is not None:
                if not persist_snapshot(
                    stopping_snapshot,
                    updated_at=self.now_provider(),
                ):
                    self.contract.mark_failed(
                        SupervisorStopReason.INTERNAL_ERROR
                    )

        final_observations = self._terminate_all()

        if self.lease_configuration is not None and leases:
            try:
                self._release_leases(
                    leases,
                    now=self.now_provider(),
                )
            except Exception:
                if self.contract.state is not SupervisorServiceState.FAILED:
                    failed_snapshot = self.contract.mark_failed(
                        SupervisorStopReason.INTERNAL_ERROR
                    )
                    if self.runtime_checkpoint_configuration is not None:
                        persist_snapshot(
                            failed_snapshot,
                            updated_at=self.now_provider(),
                        )

        if self.contract.state is SupervisorServiceState.STOPPING:
            if self.runtime_checkpoint_configuration is None:
                self.contract.mark_stopped()
            else:
                current = self.contract.snapshot()
                stopped_candidate = SupervisorServiceSnapshot(
                    service_id=current.service_id,
                    state=SupervisorServiceState.STOPPED,
                    worker_ids=current.worker_ids,
                    stop_reason=current.stop_reason,
                )
                if persist_snapshot(
                    stopped_candidate,
                    updated_at=self.now_provider(),
                ):
                    self.contract.mark_stopped()
                else:
                    failed_snapshot = self.contract.mark_failed(
                        SupervisorStopReason.INTERNAL_ERROR
                    )
                    persist_snapshot(
                        failed_snapshot,
                        updated_at=self.now_provider(),
                    )

        return report(final_observations)

