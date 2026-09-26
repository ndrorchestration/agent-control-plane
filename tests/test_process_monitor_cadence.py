import sys
import time

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


def build(tmp_path, *, command):
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="relay-a",
            argv=(sys.executable, "-c", command),
        )
    )
    tick = ProcessMonitorTick(
        controller=controller,
        policy=ProcessSupervisionPolicy(
            max_restarts=1,
            min_restart_interval_seconds=0,
        ),
        failure_store=DurableProcessFailureStore(
            tmp_path / "failures.sqlite3"
        ),
    )
    scheduler = ScheduledProcessMonitor(
        monitor_tick=tick,
        cadence_store=DurableProcessMonitorCadenceStore(
            tmp_path / "cadence.sqlite3"
        ),
        cadence_policy=ProcessMonitorCadencePolicy(
            min_interval_seconds=10,
        ),
    )
    return controller, scheduler


def test_first_tick_is_due_and_records_next_due(tmp_path):
    controller, scheduler = build(
        tmp_path,
        command="import time; time.sleep(30)",
    )
    controller.start()
    try:
        result = scheduler.run_if_due(
            now="2026-09-25T22:00:00Z"
        )
        assert result.ran is True
        assert result.next_due_at == "2026-09-25T22:00:10Z"
    finally:
        controller.terminate(timeout_seconds=2)


def test_tick_before_interval_is_deferred(tmp_path):
    controller, scheduler = build(
        tmp_path,
        command="import time; time.sleep(30)",
    )
    controller.start()
    try:
        scheduler.run_if_due(now="2026-09-25T22:00:00Z")
        result = scheduler.run_if_due(
            now="2026-09-25T22:00:05Z"
        )
        assert result.ran is False
        assert result.next_due_at == "2026-09-25T22:00:10Z"
        assert result.tick_result is None
    finally:
        controller.terminate(timeout_seconds=2)


def test_tick_at_interval_runs_again(tmp_path):
    controller, scheduler = build(
        tmp_path,
        command="import time; time.sleep(30)",
    )
    controller.start()
    try:
        scheduler.run_if_due(now="2026-09-25T22:00:00Z")
        result = scheduler.run_if_due(
            now="2026-09-25T22:00:10Z"
        )
        assert result.ran is True
        assert result.next_due_at == "2026-09-25T22:00:20Z"
    finally:
        controller.terminate(timeout_seconds=2)


def test_cadence_survives_store_reopen(tmp_path):
    path = tmp_path / "cadence.sqlite3"
    first = DurableProcessMonitorCadenceStore(path)
    first.record_tick(
        process_id="relay-a",
        ticked_at="2026-09-25T22:00:00Z",
    )
    reopened = DurableProcessMonitorCadenceStore(path)
    state = reopened.get("relay-a")
    policy = ProcessMonitorCadencePolicy(min_interval_seconds=10)
    assert policy.due(
        state,
        now="2026-09-25T22:00:05Z",
    ) is False
    assert policy.due(
        state,
        now="2026-09-25T22:00:10Z",
    ) is True


def test_due_tick_can_detect_crash_and_restart(tmp_path):
    controller, scheduler = build(
        tmp_path,
        command="raise SystemExit(3)",
    )
    controller.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not controller.observe().running:
            break
        time.sleep(0.05)

    result = scheduler.run_if_due(
        now="2026-09-25T22:00:00Z"
    )
    assert result.ran is True
    assert result.tick_result.decision.value == "restart"
