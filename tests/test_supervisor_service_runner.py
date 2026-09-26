import sys

from agent_control_plane.process_monitor import (
    DurableProcessFailureStore,
    ProcessMonitorTick,
)
from agent_control_plane.process_monitor_cadence import (
    DurableProcessMonitorCadenceStore,
    ProcessMonitorCadencePolicy,
    ScheduledProcessMonitor,
)
from agent_control_plane.process_runtime import (
    ManagedProcessController,
    ManagedProcessSpec,
)
from agent_control_plane.process_supervision import ProcessSupervisionPolicy
from agent_control_plane.supervisor_service import (
    SupervisorServiceContract,
    SupervisorServiceState,
    SupervisorStopReason,
    SupervisorWorkerRegistration,
)
from agent_control_plane.supervisor_ownership import (
    SupervisorOwnershipLeaseStore,
)
from agent_control_plane.supervisor_runtime_checkpoint import (
    DurableSupervisorRuntimeCheckpointStore,
    SupervisorPreviousRunDisposition,
)
from agent_control_plane.supervisor_service_runner import (
    BoundedSupervisorServiceRunner,
    SupervisorLeaseConfiguration,
    SupervisorRuntimeCheckpointConfiguration,
    SupervisorWorkerRuntime,
)


def worker(tmp_path, worker_id):
    process_id = f"{worker_id}-process"
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id=process_id,
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ),
        )
    )
    monitor = ProcessMonitorTick(
        controller=controller,
        policy=ProcessSupervisionPolicy(
            max_restarts=1,
            min_restart_interval_seconds=0,
        ),
        failure_store=DurableProcessFailureStore(
            tmp_path / f"{worker_id}-failure.sqlite3"
        ),
    )
    scheduler = ScheduledProcessMonitor(
        monitor_tick=monitor,
        cadence_store=DurableProcessMonitorCadenceStore(
            tmp_path / f"{worker_id}-cadence.sqlite3"
        ),
        cadence_policy=ProcessMonitorCadencePolicy(
            min_interval_seconds=1,
        ),
    )
    registration = SupervisorWorkerRegistration(
        worker_id=worker_id,
        process_id=process_id,
        ownership_token=f"owner-{worker_id}",
    )
    return SupervisorWorkerRuntime(
        registration=registration,
        controller=controller,
        scheduler=scheduler,
    )


def service_for(workers):
    return SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=tuple(worker.registration for worker in workers),
    )


def test_sigterm_stops_workers_and_latches_signal_reason(tmp_path):
    workers = (
        worker(tmp_path, "relay-a"),
        worker(tmp_path, "relay-b"),
    )
    contract = service_for(workers)
    times = iter([
        "2026-09-25T22:00:00Z",
        "2026-09-25T22:00:01Z",
    ])

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=4,
        interval_seconds=0,
        now_provider=lambda: next(times),
        sleep_fn=lambda seconds: None,
        signal_provider=lambda index: "SIGTERM" if index == 1 else None,
        terminate_timeout_seconds=2,
    )
    report = runner.run()

    assert report.final_snapshot.state is SupervisorServiceState.STOPPED
    assert (
        report.final_snapshot.stop_reason
        is SupervisorStopReason.SIGNAL_TERM
    )
    assert report.cycles_completed == 1
    assert all(
        observation.running is False
        for observation in report.final_observations
    )


def test_sigint_before_first_cycle_prevents_monitor_work(tmp_path):
    workers = (worker(tmp_path, "relay-a"),)
    contract = service_for(workers)

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=3,
        interval_seconds=0,
        now_provider=lambda: "2026-09-25T22:00:00Z",
        sleep_fn=lambda seconds: None,
        signal_provider=lambda index: "SIGINT" if index == 0 else None,
        terminate_timeout_seconds=2,
    )
    report = runner.run()

    assert report.cycles_completed == 0
    assert report.cycle_records == ()
    assert (
        report.final_snapshot.stop_reason
        is SupervisorStopReason.SIGNAL_INT
    )
    assert report.final_snapshot.state is SupervisorServiceState.STOPPED


def test_finite_completion_stops_all_workers(tmp_path):
    workers = (
        worker(tmp_path, "relay-a"),
        worker(tmp_path, "relay-b"),
    )
    contract = service_for(workers)
    times = iter([
        "2026-09-25T22:00:00Z",
        "2026-09-25T22:00:01Z",
    ])

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=2,
        interval_seconds=0,
        now_provider=lambda: next(times),
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
    )
    report = runner.run()

    assert report.cycles_completed == 2
    assert (
        report.final_snapshot.stop_reason
        is SupervisorStopReason.OPERATOR_REQUEST
    )
    assert report.final_snapshot.state is SupervisorServiceState.STOPPED
    assert all(
        observation.running is False
        for observation in report.final_observations
    )


def test_worker_runtime_order_must_match_contract(tmp_path):
    workers = (
        worker(tmp_path, "relay-a"),
        worker(tmp_path, "relay-b"),
    )
    contract = service_for(workers)

    import pytest
    from agent_control_plane.authority import AuthorityValidationError

    with pytest.raises(
        AuthorityValidationError,
        match="must exactly match",
    ):
        BoundedSupervisorServiceRunner(
            contract=contract,
            workers=tuple(reversed(workers)),
            max_cycles=1,
            interval_seconds=0,
            now_provider=lambda: "2026-09-25T22:00:00Z",
            sleep_fn=lambda seconds: None,
        )



def test_lease_enforced_run_acquires_renews_and_releases(tmp_path):
    workers = (worker(tmp_path, "relay-a"),)
    contract = service_for(workers)
    store = SupervisorOwnershipLeaseStore(
        tmp_path / "ownership.sqlite3"
    )
    times = iter([
        "2026-09-25T22:00:00Z",
        "2026-09-25T22:00:01Z",
        "2026-09-25T22:00:02Z",
    ])

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=1,
        interval_seconds=0,
        now_provider=lambda: next(times),
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=store,
            owner_id="acp-supervisor",
            instance_token="instance-1",
            ttl_seconds=10,
        ),
    )
    report = runner.run()

    lease = store.get("relay-a-process")
    assert lease is not None
    assert lease.released_at == "2026-09-25T22:00:02Z"
    assert report.lease_fencing_tokens == (
        ("relay-a-process", 1),
    )
    assert report.final_snapshot.state is SupervisorServiceState.STOPPED


def test_competing_active_lease_blocks_worker_startup(tmp_path):
    workers = (worker(tmp_path, "relay-a"),)
    contract = service_for(workers)
    store = SupervisorOwnershipLeaseStore(
        tmp_path / "ownership.sqlite3"
    )
    store.acquire(
        resource_id="relay-a-process",
        owner_id="other-supervisor",
        ownership_token="other-instance:owner-relay-a",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=30,
    )

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=1,
        interval_seconds=0,
        now_provider=lambda: "2026-09-25T22:00:01Z",
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=store,
            owner_id="acp-supervisor",
            instance_token="instance-1",
            ttl_seconds=10,
        ),
    )
    report = runner.run()

    assert report.final_snapshot.state is SupervisorServiceState.FAILED
    assert (
        report.final_snapshot.stop_reason
        is SupervisorStopReason.STARTUP_FAILURE
    )
    assert report.cycles_completed == 0
    assert report.final_observations[0].pid is None
    assert report.final_observations[0].running is False


def test_stale_fence_stops_service_before_next_monitor_cycle(tmp_path):
    workers = (worker(tmp_path, "relay-a"),)
    contract = service_for(workers)
    store = SupervisorOwnershipLeaseStore(
        tmp_path / "ownership.sqlite3"
    )
    times = iter([
        "2026-09-25T22:00:00Z",
        "2026-09-25T22:00:00Z",
        "2026-09-25T22:00:02Z",
        "2026-09-25T22:00:03Z",
    ])

    def takeover(_seconds):
        store.acquire(
            resource_id="relay-a-process",
            owner_id="other-supervisor",
            ownership_token="other-instance:owner-relay-a",
            now="2026-09-25T22:00:02Z",
            ttl_seconds=10,
        )

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=2,
        interval_seconds=0,
        now_provider=lambda: next(times),
        sleep_fn=takeover,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=store,
            owner_id="acp-supervisor",
            instance_token="instance-1",
            ttl_seconds=1,
        ),
    )
    report = runner.run()

    assert report.cycles_completed == 1
    assert report.final_snapshot.state is SupervisorServiceState.FAILED
    assert (
        report.final_snapshot.stop_reason
        is SupervisorStopReason.INTERNAL_ERROR
    )
    assert report.final_observations[0].running is False
    current = store.get("relay-a-process")
    assert current is not None
    assert current.owner_id == "other-supervisor"
    assert current.fencing_token == 2



def test_checkpointed_run_persists_clean_terminal_state(tmp_path):
    workers = (worker(tmp_path, "relay-a"),)
    contract = service_for(workers)
    lease_store = SupervisorOwnershipLeaseStore(
        tmp_path / "ownership-runtime.sqlite3"
    )
    runtime_store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime.sqlite3"
    )
    times = iter([
        "2026-09-25T23:00:00Z",  # acquire + begin run
        "2026-09-25T23:00:01Z",  # running checkpoint
        "2026-09-25T23:00:02Z",  # cycle + lease renewal
        "2026-09-25T23:00:03Z",  # stop requested
        "2026-09-25T23:00:04Z",  # stopping
        "2026-09-25T23:00:05Z",  # lease release
        "2026-09-25T23:00:06Z",  # stopped checkpoint
    ])

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=1,
        interval_seconds=0,
        now_provider=lambda: next(times),
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=lease_store,
            owner_id="acp-supervisor",
            instance_token="runtime-instance-1",
            ttl_seconds=30,
        ),
        runtime_checkpoint_configuration=(
            SupervisorRuntimeCheckpointConfiguration(
                store=runtime_store,
            )
        ),
    )
    report = runner.run()

    persisted = runtime_store.get("acp-supervisor")
    assert persisted is not None
    assert persisted.state is SupervisorServiceState.STOPPED
    assert (
        persisted.stop_reason
        is SupervisorStopReason.OPERATOR_REQUEST
    )
    assert report.runtime_generation == 1
    assert report.service_lease_fencing_token == 1
    assert (
        report.runtime_recovery.disposition
        is SupervisorPreviousRunDisposition.FRESH
    )
    assert report.lease_fencing_tokens == (
        ("relay-a-process", 1),
    )
    service_lease = lease_store.get("service:acp-supervisor")
    assert service_lease is not None
    assert service_lease.released_at == "2026-09-25T23:00:05Z"


def test_next_checkpointed_run_classifies_prior_clean_stop(tmp_path):
    lease_store = SupervisorOwnershipLeaseStore(
        tmp_path / "ownership-runtime.sqlite3"
    )
    runtime_store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime.sqlite3"
    )

    first_workers = (worker(tmp_path, "relay-a"),)
    first_contract = service_for(first_workers)
    first_times = iter([
        "2026-09-25T23:00:00Z",
        "2026-09-25T23:00:01Z",
        "2026-09-25T23:00:02Z",
        "2026-09-25T23:00:03Z",
        "2026-09-25T23:00:04Z",
        "2026-09-25T23:00:05Z",
        "2026-09-25T23:00:06Z",
    ])
    first = BoundedSupervisorServiceRunner(
        contract=first_contract,
        workers=first_workers,
        max_cycles=1,
        interval_seconds=0,
        now_provider=lambda: next(first_times),
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=lease_store,
            owner_id="acp-supervisor",
            instance_token="runtime-instance-1",
            ttl_seconds=30,
        ),
        runtime_checkpoint_configuration=(
            SupervisorRuntimeCheckpointConfiguration(
                store=runtime_store,
            )
        ),
    )
    assert first.run().runtime_generation == 1

    second_workers = (worker(tmp_path, "relay-a-second"),)
    # Keep the same process/resource identity across generations.
    second_workers[0].controller.spec.__dict__ if False else None
    second_registration = SupervisorWorkerRegistration(
        worker_id="relay-a",
        process_id="relay-a-process",
        ownership_token="owner-relay-a",
    )
    second_controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="relay-a-process",
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ),
        )
    )
    second_monitor = ProcessMonitorTick(
        controller=second_controller,
        policy=ProcessSupervisionPolicy(
            max_restarts=1,
            min_restart_interval_seconds=0,
        ),
        failure_store=DurableProcessFailureStore(
            tmp_path / "relay-a-second-failure.sqlite3"
        ),
    )
    second_scheduler = ScheduledProcessMonitor(
        monitor_tick=second_monitor,
        cadence_store=DurableProcessMonitorCadenceStore(
            tmp_path / "relay-a-second-cadence.sqlite3"
        ),
        cadence_policy=ProcessMonitorCadencePolicy(
            min_interval_seconds=1,
        ),
    )
    second_runtime = SupervisorWorkerRuntime(
        registration=second_registration,
        controller=second_controller,
        scheduler=second_scheduler,
    )
    second_contract = SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=(second_registration,),
    )
    second_times = iter([
        "2026-09-25T23:01:00Z",
        "2026-09-25T23:01:01Z",
        "2026-09-25T23:01:02Z",
        "2026-09-25T23:01:03Z",
        "2026-09-25T23:01:04Z",
        "2026-09-25T23:01:05Z",
        "2026-09-25T23:01:06Z",
    ])
    second = BoundedSupervisorServiceRunner(
        contract=second_contract,
        workers=(second_runtime,),
        max_cycles=1,
        interval_seconds=0,
        now_provider=lambda: next(second_times),
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=lease_store,
            owner_id="acp-supervisor",
            instance_token="runtime-instance-2",
            ttl_seconds=30,
        ),
        runtime_checkpoint_configuration=(
            SupervisorRuntimeCheckpointConfiguration(
                store=runtime_store,
            )
        ),
    )
    report = second.run()

    assert report.runtime_generation == 2
    assert (
        report.runtime_recovery.disposition
        is SupervisorPreviousRunDisposition.CLEAN_STOP
    )
    assert report.service_lease_fencing_token == 2


def test_checkpointed_run_reports_unclean_prior_generation(tmp_path):
    lease_store = SupervisorOwnershipLeaseStore(
        tmp_path / "ownership-unclean.sqlite3"
    )
    runtime_store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime-unclean.sqlite3"
    )
    prior = runtime_store.begin_run(
        service_id="acp-supervisor",
        owner_id="old-supervisor",
        fencing_token=9,
        started_at="2026-09-25T22:00:00Z",
    )
    prior_contract = SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=(
            SupervisorWorkerRegistration(
                worker_id="relay-a",
                process_id="relay-a-process",
                ownership_token="owner-relay-a",
            ),
        ),
    )
    prior_contract.begin_startup()
    runtime_store.write_snapshot(
        prior.checkpoint,
        prior_contract.mark_running(),
        updated_at="2026-09-25T22:00:01Z",
    )

    workers = (worker(tmp_path, "relay-a"),)
    contract = service_for(workers)
    times = iter([
        "2026-09-25T23:00:00Z",
        "2026-09-25T23:00:01Z",
        "2026-09-25T23:00:02Z",
        "2026-09-25T23:00:03Z",
        "2026-09-25T23:00:04Z",
        "2026-09-25T23:00:05Z",
        "2026-09-25T23:00:06Z",
    ])
    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=workers,
        max_cycles=1,
        interval_seconds=0,
        now_provider=lambda: next(times),
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=lease_store,
            owner_id="acp-supervisor",
            instance_token="runtime-instance-new",
            ttl_seconds=30,
        ),
        runtime_checkpoint_configuration=(
            SupervisorRuntimeCheckpointConfiguration(
                store=runtime_store,
            )
        ),
    )
    report = runner.run()

    assert (
        report.runtime_recovery.disposition
        is SupervisorPreviousRunDisposition.UNCLEAN_EXIT
    )
    assert report.runtime_recovery.stale_owner is True


def test_startup_failure_is_persisted_and_leases_are_released(tmp_path):
    registration = SupervisorWorkerRegistration(
        worker_id="broken",
        process_id="broken-process",
        ownership_token="owner-broken",
    )
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="broken-process",
            argv=("definitely-not-an-executable-acp-test",),
        )
    )
    monitor = ProcessMonitorTick(
        controller=controller,
        policy=ProcessSupervisionPolicy(max_restarts=1),
        failure_store=DurableProcessFailureStore(
            tmp_path / "broken-failure.sqlite3"
        ),
    )
    scheduler = ScheduledProcessMonitor(
        monitor_tick=monitor,
        cadence_store=DurableProcessMonitorCadenceStore(
            tmp_path / "broken-cadence.sqlite3"
        ),
        cadence_policy=ProcessMonitorCadencePolicy(
            min_interval_seconds=1,
        ),
    )
    runtime = SupervisorWorkerRuntime(
        registration=registration,
        controller=controller,
        scheduler=scheduler,
    )
    contract = SupervisorServiceContract(
        service_id="broken-supervisor",
        workers=(registration,),
    )
    lease_store = SupervisorOwnershipLeaseStore(
        tmp_path / "broken-ownership.sqlite3"
    )
    runtime_store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "broken-runtime.sqlite3"
    )
    times = iter([
        "2026-09-25T23:00:00Z",
        "2026-09-25T23:00:01Z",
        "2026-09-25T23:00:02Z",
    ])

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=(runtime,),
        max_cycles=1,
        interval_seconds=0,
        now_provider=lambda: next(times),
        sleep_fn=lambda seconds: None,
        terminate_timeout_seconds=2,
        lease_configuration=SupervisorLeaseConfiguration(
            store=lease_store,
            owner_id="broken-supervisor",
            instance_token="broken-instance",
            ttl_seconds=30,
        ),
        runtime_checkpoint_configuration=(
            SupervisorRuntimeCheckpointConfiguration(
                store=runtime_store,
            )
        ),
    )
    report = runner.run()

    assert report.final_snapshot.state is SupervisorServiceState.FAILED
    persisted = runtime_store.get("broken-supervisor")
    assert persisted is not None
    assert persisted.state is SupervisorServiceState.FAILED
    assert (
        persisted.stop_reason
        is SupervisorStopReason.STARTUP_FAILURE
    )
    assert lease_store.get("service:broken-supervisor").released_at is not None
    assert lease_store.get("broken-process").released_at is not None
