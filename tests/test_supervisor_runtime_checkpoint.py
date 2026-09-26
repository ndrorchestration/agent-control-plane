from agent_control_plane.supervisor_runtime_checkpoint import (
    DurableSupervisorRuntimeCheckpointStore,
    SupervisorPreviousRunDisposition,
)
from agent_control_plane.supervisor_service import (
    SupervisorServiceContract,
    SupervisorStopReason,
    SupervisorWorkerRegistration,
)


def contract():
    return SupervisorServiceContract(
        service_id="acp-supervisor",
        workers=(
            SupervisorWorkerRegistration(
                worker_id="relay-a",
                process_id="relay-a-process",
                ownership_token="owner-relay-a",
            ),
        ),
    )


def test_fresh_start_creates_generation_one(tmp_path):
    store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime.sqlite3"
    )
    started = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=1,
        started_at="2026-09-25T22:00:00Z",
    )
    assert started.checkpoint.generation == 1
    assert (
        started.recovery.disposition
        is SupervisorPreviousRunDisposition.FRESH
    )
    assert started.recovery.stale_owner is False


def test_clean_stop_is_classified_on_next_generation(tmp_path):
    store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime.sqlite3"
    )
    started = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=1,
        started_at="2026-09-25T22:00:00Z",
    )
    service = contract()
    service.begin_startup()
    cp = store.write_snapshot(
        started.checkpoint,
        service.mark_running(),
        updated_at="2026-09-25T22:00:01Z",
    )
    cp = store.write_snapshot(
        cp,
        service.request_stop(SupervisorStopReason.OPERATOR_REQUEST),
        updated_at="2026-09-25T22:00:02Z",
    )
    cp = store.write_snapshot(
        cp,
        service.begin_stopping(),
        updated_at="2026-09-25T22:00:03Z",
    )
    store.write_snapshot(
        cp,
        service.mark_stopped(),
        updated_at="2026-09-25T22:00:04Z",
    )

    next_run = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=2,
        started_at="2026-09-25T22:01:00Z",
    )
    assert next_run.checkpoint.generation == 2
    assert (
        next_run.recovery.disposition
        is SupervisorPreviousRunDisposition.CLEAN_STOP
    )


def test_running_checkpoint_is_classified_unclean_after_restart(tmp_path):
    store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime.sqlite3"
    )
    started = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=1,
        started_at="2026-09-25T22:00:00Z",
    )
    service = contract()
    service.begin_startup()
    store.write_snapshot(
        started.checkpoint,
        service.mark_running(),
        updated_at="2026-09-25T22:00:01Z",
    )

    next_run = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-2",
        fencing_token=2,
        started_at="2026-09-25T22:01:00Z",
    )
    assert (
        next_run.recovery.disposition
        is SupervisorPreviousRunDisposition.UNCLEAN_EXIT
    )
    assert next_run.recovery.stale_owner is True


def test_worker_give_up_is_terminal_give_up(tmp_path):
    store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime.sqlite3"
    )
    started = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=1,
        started_at="2026-09-25T22:00:00Z",
    )
    service = contract()
    service.begin_startup()
    cp = store.write_snapshot(
        started.checkpoint,
        service.mark_running(),
        updated_at="2026-09-25T22:00:01Z",
    )
    cp = store.write_snapshot(
        cp,
        service.request_stop(SupervisorStopReason.WORKER_GIVE_UP),
        updated_at="2026-09-25T22:00:02Z",
    )
    store.write_snapshot(
        cp,
        service.mark_failed(SupervisorStopReason.WORKER_GIVE_UP),
        updated_at="2026-09-25T22:00:03Z",
    )

    next_run = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=2,
        started_at="2026-09-25T22:01:00Z",
    )
    assert (
        next_run.recovery.disposition
        is SupervisorPreviousRunDisposition.TERMINAL_GIVE_UP
    )


def test_stale_generation_cannot_write_after_new_run_begins(tmp_path):
    import pytest
    from agent_control_plane.authority import AuthorityValidationError

    store = DurableSupervisorRuntimeCheckpointStore(
        tmp_path / "runtime.sqlite3"
    )
    first = store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=1,
        started_at="2026-09-25T22:00:00Z",
    )
    store.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-2",
        fencing_token=2,
        started_at="2026-09-25T22:01:00Z",
    )
    service = contract()
    service.begin_startup()

    with pytest.raises(
        AuthorityValidationError,
        match="stale supervisor runtime checkpoint",
    ):
        store.write_snapshot(
            first.checkpoint,
            service.mark_running(),
            updated_at="2026-09-25T22:01:01Z",
        )


def test_checkpoint_survives_store_reopen(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    first = DurableSupervisorRuntimeCheckpointStore(path)
    started = first.begin_run(
        service_id="acp-supervisor",
        owner_id="supervisor-1",
        fencing_token=3,
        started_at="2026-09-25T22:00:00Z",
    )
    reopened = DurableSupervisorRuntimeCheckpointStore(path)
    assert reopened.get("acp-supervisor") == started.checkpoint
