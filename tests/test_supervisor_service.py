import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.supervisor_service import (
    SupervisorServiceContract,
    SupervisorServiceState,
    SupervisorStopReason,
    SupervisorWorkerRegistration,
)


def workers():
    return (
        SupervisorWorkerRegistration(
            worker_id="relay-a",
            process_id="relay-a-process",
            ownership_token="owner-a",
        ),
        SupervisorWorkerRegistration(
            worker_id="relay-b",
            process_id="relay-b-process",
            ownership_token="owner-b",
        ),
    )


def test_normal_service_lifecycle():
    service = SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=workers(),
    )
    assert service.snapshot().state is SupervisorServiceState.CREATED
    assert service.begin_startup().state is SupervisorServiceState.STARTING
    assert service.mark_running().state is SupervisorServiceState.RUNNING
    stopped = service.request_stop(
        SupervisorStopReason.OPERATOR_REQUEST
    )
    assert stopped.state is SupervisorServiceState.STOP_REQUESTED
    assert stopped.stop_reason is SupervisorStopReason.OPERATOR_REQUEST
    assert service.begin_stopping().state is SupervisorServiceState.STOPPING
    assert service.mark_stopped().state is SupervisorServiceState.STOPPED


def test_sigterm_and_sigint_map_to_explicit_stop_reasons():
    term = SupervisorServiceContract(
        service_id="term",
        workers=workers(),
    )
    term.begin_startup()
    term.mark_running()
    snapshot = term.handle_signal("SIGTERM")
    assert snapshot.stop_reason is SupervisorStopReason.SIGNAL_TERM

    intr = SupervisorServiceContract(
        service_id="int",
        workers=workers(),
    )
    intr.begin_startup()
    intr.mark_running()
    snapshot = intr.handle_signal("SIGINT")
    assert snapshot.stop_reason is SupervisorStopReason.SIGNAL_INT


def test_duplicate_worker_process_or_ownership_is_rejected():
    with pytest.raises(AuthorityValidationError, match="duplicate worker_id"):
        SupervisorServiceContract(
            service_id="bad",
            workers=(
                workers()[0],
                SupervisorWorkerRegistration(
                    worker_id="relay-a",
                    process_id="other-process",
                    ownership_token="other-owner",
                ),
            ),
        )

    with pytest.raises(AuthorityValidationError, match="duplicate process_id"):
        SupervisorServiceContract(
            service_id="bad",
            workers=(
                workers()[0],
                SupervisorWorkerRegistration(
                    worker_id="other-worker",
                    process_id="relay-a-process",
                    ownership_token="other-owner",
                ),
            ),
        )

    with pytest.raises(
        AuthorityValidationError,
        match="duplicate ownership_token",
    ):
        SupervisorServiceContract(
            service_id="bad",
            workers=(
                workers()[0],
                SupervisorWorkerRegistration(
                    worker_id="other-worker",
                    process_id="other-process",
                    ownership_token="owner-a",
                ),
            ),
        )


def test_invalid_lifecycle_transitions_fail_closed():
    service = SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=workers(),
    )
    with pytest.raises(AuthorityValidationError):
        service.mark_running()
    service.begin_startup()
    with pytest.raises(AuthorityValidationError):
        service.mark_stopped()


def test_failure_is_terminal_and_records_reason():
    service = SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=workers(),
    )
    service.begin_startup()
    snapshot = service.mark_failed(
        SupervisorStopReason.STARTUP_FAILURE
    )
    assert snapshot.state is SupervisorServiceState.FAILED
    assert snapshot.stop_reason is SupervisorStopReason.STARTUP_FAILURE
    with pytest.raises(AuthorityValidationError):
        service.request_stop(SupervisorStopReason.OPERATOR_REQUEST)


def test_unknown_signal_fails_closed():
    service = SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=workers(),
    )
    service.begin_startup()
    service.mark_running()
    with pytest.raises(
        AuthorityValidationError,
        match="unsupported supervisor signal",
    ):
        service.handle_signal("SIGHUP")
