import sys
import time

from agent_control_plane.process_monitor import (
    DurableProcessFailureStore,
    ProcessMonitorTick,
)
from agent_control_plane.process_runtime import (
    ManagedProcessController,
    ManagedProcessSpec,
)
from agent_control_plane.process_supervision import (
    ProcessSupervisionDecision,
    ProcessSupervisionPolicy,
)


def wait_until_exited(controller, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observation = controller.observe()
        if not observation.running:
            return observation
        time.sleep(0.05)
    raise AssertionError("process did not exit")


def test_running_process_tick_is_noop(tmp_path):
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
    try:
        tick = ProcessMonitorTick(
            controller=controller,
            policy=ProcessSupervisionPolicy(max_restarts=2),
            failure_store=DurableProcessFailureStore(
                tmp_path / "failures.sqlite3"
            ),
        )
        result = tick.run(now="2026-09-25T22:00:00Z")
        assert result.decision is None
        assert result.observation_after.running is True
        assert result.failure_state is None
    finally:
        controller.terminate(timeout_seconds=2)


def test_exited_process_is_detected_persisted_and_restarted(tmp_path):
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="relay-a",
            argv=(
                sys.executable,
                "-c",
                "print('boom')",
            ),
        )
    )
    controller.start()
    wait_until_exited(controller)

    store = DurableProcessFailureStore(tmp_path / "failures.sqlite3")
    tick = ProcessMonitorTick(
        controller=controller,
        policy=ProcessSupervisionPolicy(
            max_restarts=2,
            min_restart_interval_seconds=0,
        ),
        failure_store=store,
    )
    result = tick.run(now="2026-09-25T22:00:00Z")
    assert result.decision is ProcessSupervisionDecision.RESTART
    assert result.failure_state.failure_count == 1
    assert result.failure_state.last_restart_at == "2026-09-25T22:00:00Z"
    wait_until_exited(controller)


def test_failure_count_survives_store_reopen(tmp_path):
    path = tmp_path / "failures.sqlite3"
    first = DurableProcessFailureStore(path)
    first.record_failure(
        process_id="relay-a",
        failed_at="2026-09-25T22:00:00Z",
    )
    first.record_restart(
        process_id="relay-a",
        restarted_at="2026-09-25T22:00:01Z",
    )

    reopened = DurableProcessFailureStore(path)
    state = reopened.get("relay-a")
    assert state.failure_count == 1
    assert state.last_restart_at == "2026-09-25T22:00:01Z"


def test_repeated_failures_reach_give_up(tmp_path):
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="relay-a",
            argv=(
                sys.executable,
                "-c",
                "raise SystemExit(7)",
            ),
        )
    )
    store = DurableProcessFailureStore(tmp_path / "failures.sqlite3")
    tick = ProcessMonitorTick(
        controller=controller,
        policy=ProcessSupervisionPolicy(
            max_restarts=1,
            min_restart_interval_seconds=0,
        ),
        failure_store=store,
    )

    controller.start()
    wait_until_exited(controller)
    first = tick.run(now="2026-09-25T22:00:00Z")
    assert first.decision is ProcessSupervisionDecision.RESTART

    wait_until_exited(controller)
    second = tick.run(now="2026-09-25T22:00:01Z")
    assert second.decision is ProcessSupervisionDecision.GIVE_UP
    assert second.failure_state.failure_count == 2
    assert second.observation_after.running is False


def test_never_started_process_is_not_counted_as_failure(tmp_path):
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="relay-a",
            argv=(sys.executable, "-c", "print('unused')"),
        )
    )
    store = DurableProcessFailureStore(tmp_path / "failures.sqlite3")
    tick = ProcessMonitorTick(
        controller=controller,
        policy=ProcessSupervisionPolicy(max_restarts=1),
        failure_store=store,
    )
    result = tick.run(now="2026-09-25T22:00:00Z")
    assert result.decision is None
    assert result.failure_state is None
    assert store.get("relay-a") is None
