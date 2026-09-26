import sys
import time

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.process_runtime import (
    ManagedProcessController,
    ManagedProcessSpec,
    SupervisedProcessController,
)
from agent_control_plane.process_supervision import (
    ProcessFailureState,
    ProcessSupervisionDecision,
    ProcessSupervisionPolicy,
)


def test_real_short_lived_process_can_start_and_observe():
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="short",
            argv=(
                sys.executable,
                "-c",
                "print('ok')",
            ),
        )
    )
    started = controller.start()
    assert started.pid is not None

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        observed = controller.observe()
        if not observed.running:
            break
        time.sleep(0.05)

    assert observed.running is False
    assert observed.returncode == 0
    assert "ok" in controller.read_output()


def test_long_running_process_can_be_terminated():
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="long",
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ),
        )
    )
    assert controller.start().running is True
    stopped = controller.terminate(timeout_seconds=2)
    assert stopped.running is False
    assert stopped.returncode is not None


def test_restart_replaces_process_instance():
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="restartable",
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ),
        )
    )
    first = controller.start()
    second = controller.restart(timeout_seconds=2)
    try:
        assert first.pid != second.pid
        assert second.running is True
    finally:
        controller.terminate(timeout_seconds=2)


def test_double_start_fails_closed():
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="double",
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ),
        )
    )
    controller.start()
    try:
        with pytest.raises(
            AuthorityValidationError,
            match="already running",
        ):
            controller.start()
    finally:
        controller.terminate(timeout_seconds=2)


def test_supervised_restart_executes_restart_decision():
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
    supervised = SupervisedProcessController(
        controller=controller,
        policy=ProcessSupervisionPolicy(
            max_restarts=3,
            min_restart_interval_seconds=0,
        ),
    )
    try:
        result = supervised.handle_failure(
            ProcessFailureState(
                process_id="relay-a",
                failure_count=1,
                last_failure_at="2026-09-25T21:00:00Z",
            ),
            now="2026-09-25T21:00:01Z",
            timeout_seconds=2,
        )
        assert result.decision is ProcessSupervisionDecision.RESTART
        assert result.observation.running is True
    finally:
        controller.terminate(timeout_seconds=2)


def test_supervised_hold_does_not_restart():
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
    first = controller.start()
    supervised = SupervisedProcessController(
        controller=controller,
        policy=ProcessSupervisionPolicy(
            max_restarts=3,
            min_restart_interval_seconds=10,
        ),
    )
    try:
        result = supervised.handle_failure(
            ProcessFailureState(
                process_id="relay-a",
                failure_count=2,
                last_failure_at="2026-09-25T21:00:05Z",
                last_restart_at="2026-09-25T21:00:00Z",
            ),
            now="2026-09-25T21:00:05Z",
        )
        assert result.decision is ProcessSupervisionDecision.HOLD
        assert result.observation.pid == first.pid
    finally:
        controller.terminate(timeout_seconds=2)


def test_supervised_give_up_terminates_process():
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
    supervised = SupervisedProcessController(
        controller=controller,
        policy=ProcessSupervisionPolicy(max_restarts=1),
    )
    result = supervised.handle_failure(
        ProcessFailureState(
            process_id="relay-a",
            failure_count=2,
            last_failure_at="2026-09-25T21:00:00Z",
        ),
        now="2026-09-25T21:00:01Z",
        timeout_seconds=2,
    )
    assert result.decision is ProcessSupervisionDecision.GIVE_UP
    assert result.observation.running is False


def test_spec_validation_rejects_empty_argv():
    with pytest.raises(AuthorityValidationError):
        ManagedProcessSpec(
            process_id="bad",
            argv=(),
        )



def test_terminate_uses_kill_fallback_when_child_ignores_sigterm():
    controller = ManagedProcessController(
        ManagedProcessSpec(
            process_id="ignores-term",
            argv=(
                sys.executable,
                "-c",
                (
                    "import signal,time;"
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                    "time.sleep(30)"
                ),
            ),
        )
    )
    started = controller.start()
    assert started.running is True

    time.sleep(0.1)
    stopped = controller.terminate(timeout_seconds=0.1)

    assert stopped.running is False
    assert stopped.returncode is not None
