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
from agent_control_plane.supervisor_service_runner import (
    BoundedSupervisorServiceRunner,
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
