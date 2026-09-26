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
from agent_control_plane.process_monitor_runner import (
    FiniteProcessMonitorRunner,
)
from agent_control_plane.process_runtime import (
    ManagedProcessController,
    ManagedProcessSpec,
)
from agent_control_plane.process_supervision import ProcessSupervisionPolicy


def scheduler(tmp_path):
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="relay-a",
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ),
        )
    )
    controller.start()
    monitor = ProcessMonitorTick(
        controller=controller,
        policy=ProcessSupervisionPolicy(max_restarts=1),
        failure_store=DurableProcessFailureStore(
            tmp_path / "failures.sqlite3"
        ),
    )
    scheduled = ScheduledProcessMonitor(
        monitor_tick=monitor,
        cadence_store=DurableProcessMonitorCadenceStore(
            tmp_path / "cadence.sqlite3"
        ),
        cadence_policy=ProcessMonitorCadencePolicy(
            min_interval_seconds=10,
        ),
    )
    return controller, scheduled


def test_runner_stops_exactly_at_max_cycles(tmp_path):
    controller, scheduled = scheduler(tmp_path)
    times = iter([
        "2026-09-25T22:00:00Z",
        "2026-09-25T22:00:05Z",
        "2026-09-25T22:00:10Z",
    ])
    sleeps = []
    try:
        runner = FiniteProcessMonitorRunner(
            scheduler=scheduled,
            interval_seconds=5,
            max_cycles=3,
            now_provider=lambda: next(times),
            sleep_fn=lambda seconds: sleeps.append(seconds),
        )
        result = runner.run()
        assert result.cycles_requested == 3
        assert result.cycles_completed == 3
        assert tuple(r.ran for r in result.monitor_results) == (
            True,
            False,
            True,
        )
        assert sleeps == [5.0, 5.0]
    finally:
        controller.terminate(timeout_seconds=2)


def test_single_cycle_never_sleeps(tmp_path):
    controller, scheduled = scheduler(tmp_path)
    sleeps = []
    try:
        runner = FiniteProcessMonitorRunner(
            scheduler=scheduled,
            interval_seconds=5,
            max_cycles=1,
            now_provider=lambda: "2026-09-25T22:00:00Z",
            sleep_fn=lambda seconds: sleeps.append(seconds),
        )
        result = runner.run()
        assert result.cycles_completed == 1
        assert sleeps == []
    finally:
        controller.terminate(timeout_seconds=2)


def test_runner_validation(tmp_path):
    controller, scheduled = scheduler(tmp_path)
    try:
        with pytest.raises(AuthorityValidationError):
            FiniteProcessMonitorRunner(
                scheduler=scheduled,
                interval_seconds=-1,
                max_cycles=1,
            )
        with pytest.raises(AuthorityValidationError):
            FiniteProcessMonitorRunner(
                scheduler=scheduled,
                interval_seconds=1,
                max_cycles=0,
            )
    finally:
        controller.terminate(timeout_seconds=2)
