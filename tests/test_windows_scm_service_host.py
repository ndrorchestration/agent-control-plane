import sys

import pytest

from agent_control_plane.authority import AuthorityValidationError
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
from agent_control_plane.windows_scm_adapter import WindowsScmControlCode
from agent_control_plane.windows_scm_service_host import (
    WindowsScmAcceptedControl,
    WindowsScmServiceHostContract,
    WindowsScmServiceState,
)


def test_service_main_status_lifecycle():
    host = WindowsScmServiceHostContract()
    assert host.status().state is WindowsScmServiceState.STOPPED

    pending = host.service_main_enter(
        checkpoint=1,
        wait_hint_ms=3000,
    )
    assert pending.state is WindowsScmServiceState.START_PENDING
    assert pending.accepted_controls is WindowsScmAcceptedControl.NONE
    assert pending.checkpoint == 1
    assert pending.wait_hint_ms == 3000

    running = host.mark_running()
    assert running.state is WindowsScmServiceState.RUNNING
    assert running.accepted_controls & WindowsScmAcceptedControl.STOP
    assert running.accepted_controls & WindowsScmAcceptedControl.SHUTDOWN
    assert running.accepted_controls & WindowsScmAcceptedControl.PRESHUTDOWN

    host.handler_ex(WindowsScmControlCode.STOP)
    assert host.status().state is WindowsScmServiceState.STOP_PENDING
    assert host.stop_reason() is SupervisorStopReason.SERVICE_STOP

    host.update_stop_pending(
        checkpoint=2,
        wait_hint_ms=1000,
    )
    stopped = host.mark_stopped()
    assert stopped.state is WindowsScmServiceState.STOPPED
    assert stopped.accepted_controls is WindowsScmAcceptedControl.NONE


def test_interrogate_is_status_only_and_does_not_stop():
    host = WindowsScmServiceHostContract()
    host.service_main_enter()
    host.mark_running()

    before = host.status()
    result = host.handler_ex(WindowsScmControlCode.INTERROGATE)

    assert result.host_event is None
    assert host.status() == before
    assert host.stop_reason() is None


def test_first_stop_control_is_latched():
    host = WindowsScmServiceHostContract()
    host.service_main_enter()
    host.mark_running()

    host.handler_ex(WindowsScmControlCode.STOP)
    host.handler_ex(WindowsScmControlCode.PRESHUTDOWN)

    assert host.stop_reason() is SupervisorStopReason.SERVICE_STOP
    assert host.status().state is WindowsScmServiceState.STOP_PENDING


def test_pause_and_continue_fail_closed():
    host = WindowsScmServiceHostContract()
    host.service_main_enter()
    host.mark_running()

    with pytest.raises(AuthorityValidationError):
        host.handler_ex(WindowsScmControlCode.PAUSE)
    with pytest.raises(AuthorityValidationError):
        host.handler_ex(WindowsScmControlCode.CONTINUE)


def test_invalid_status_transitions_fail_closed():
    host = WindowsScmServiceHostContract()
    with pytest.raises(AuthorityValidationError):
        host.mark_running()

    host.service_main_enter()
    with pytest.raises(AuthorityValidationError):
        host.service_main_enter()

    host.mark_running()
    with pytest.raises(AuthorityValidationError):
        host.mark_running()


def test_service_specific_exit_status_is_preserved():
    host = WindowsScmServiceHostContract()
    host.service_main_enter()
    stopped = host.mark_stopped(
        win32_exit_code=1066,
        service_specific_exit_code=17,
    )
    assert stopped.win32_exit_code == 1066
    assert stopped.service_specific_exit_code == 17


def test_scm_stop_provider_composes_with_supervisor_runner(tmp_path):
    process_id = "relay-a-process"
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
            tmp_path / "failure.sqlite3"
        ),
    )
    scheduler = ScheduledProcessMonitor(
        monitor_tick=monitor,
        cadence_store=DurableProcessMonitorCadenceStore(
            tmp_path / "cadence.sqlite3"
        ),
        cadence_policy=ProcessMonitorCadencePolicy(
            min_interval_seconds=1,
        ),
    )
    registration = SupervisorWorkerRegistration(
        worker_id="relay-a",
        process_id=process_id,
        ownership_token="owner-relay-a",
    )
    runtime = SupervisorWorkerRuntime(
        registration=registration,
        controller=controller,
        scheduler=scheduler,
    )
    contract = SupervisorServiceContract(
        service_id="windows-service-host-test",
        workers=(registration,),
    )
    host = WindowsScmServiceHostContract()
    host.service_main_enter()
    host.mark_running()

    calls = []

    def sleep_fn(seconds):
        calls.append(seconds)
        host.handler_ex(WindowsScmControlCode.STOP)

    runner = BoundedSupervisorServiceRunner(
        contract=contract,
        workers=(runtime,),
        max_cycles=3,
        interval_seconds=0,
        now_provider=lambda: "2026-09-26T08:30:00Z",
        sleep_fn=sleep_fn,
        stop_reason_provider=host.stop_reason_provider,
        terminate_timeout_seconds=2,
    )
    report = runner.run()

    assert report.cycles_completed == 1
    assert (
        report.final_snapshot.stop_reason
        is SupervisorStopReason.SERVICE_STOP
    )
    assert report.final_snapshot.state is SupervisorServiceState.STOPPED
    assert report.final_observations[0].running is False
    assert host.status().state is WindowsScmServiceState.STOP_PENDING

    host.mark_stopped()
    assert host.status().state is WindowsScmServiceState.STOPPED


def test_stop_reason_provider_validates_cycle_index():
    host = WindowsScmServiceHostContract()
    with pytest.raises(AuthorityValidationError):
        host.stop_reason_provider(-1)
