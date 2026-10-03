from __future__ import annotations

import sqlite3

import pytest

from agent_control_plane.remote_mutation_execution_closure import (
    MutationExecutionClosureRecord,
)
from agent_control_plane.remote_mutation_lineage import (
    MutationLineageError,
    RemoteMutationLineageStore,
    STATE_ABORTED_PRE_EXECUTION,
    STATE_RECOVERY_HOLD,
    STATE_TERMINAL,
)


A = "a" * 64
B = "b" * 64


def closure(
    *,
    authorization_id="authz-1",
    request_id="req-1",
    resource_id="repo:test",
    operation_id="repo.write_text_file",
    plan_sha256=A,
    evidence_sha256=B,
):
    return MutationExecutionClosureRecord(
        authorization_id=authorization_id,
        authorization_sha256=A,
        evidence_sha256=evidence_sha256,
        executor_id="executor:test",
        execution_id="exec-1",
        transaction_id="tx-1",
        request_id=request_id,
        resource_id=resource_id,
        operation_id=operation_id,
        plan_sha256=plan_sha256,
        closed=True,
        reason="closed against terminal evidence",
    )


def disposable_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_terminal_lineage_survives_store_restart(tmp_path):
    root = disposable_root(tmp_path)
    path = tmp_path / "lineage.sqlite3"
    first = RemoteMutationLineageStore(path)
    first.begin_attempt(
        transaction_id="tx-1",
        resource_id="repo:test",
        repository_root=root,
        authorization_id="authz-1",
        request_id="req-1",
        operation_id="repo.write_text_file",
        plan_sha256=A,
    )
    terminal = first.mark_terminal("tx-1", closure())
    assert terminal.state == STATE_TERMINAL

    restarted = RemoteMutationLineageStore(path)
    latest = restarted.latest(resource_id="repo:test", repository_root=root)
    assert latest is not None
    assert latest.state == STATE_TERMINAL
    assert latest.evidence_sha256 == B
    assert latest.authorization_id == "authz-1"


def test_unrelated_resource_does_not_inherit_lineage(tmp_path):
    root = disposable_root(tmp_path)
    store = RemoteMutationLineageStore(tmp_path / "lineage.sqlite3")
    store.begin_attempt(
        transaction_id="tx-1",
        resource_id="repo:one",
        repository_root=root,
        authorization_id="authz-1",
        request_id="req-1",
        operation_id="repo.write_text_file",
        plan_sha256=A,
    )
    store.mark_terminal(
        "tx-1",
        closure(resource_id="repo:one"),
    )

    assert store.latest(resource_id="repo:two", repository_root=root) is None


def test_pre_execution_abort_is_durable_but_not_terminal(tmp_path):
    root = disposable_root(tmp_path)
    store = RemoteMutationLineageStore(tmp_path / "lineage.sqlite3")
    store.begin_attempt(
        transaction_id="tx-1",
        resource_id="repo:test",
        repository_root=root,
        authorization_id="authz-1",
        request_id="req-1",
        operation_id="repo.write_text_file",
        plan_sha256=A,
    )
    record = store.mark_aborted_pre_execution("tx-1", reason="authorization expired")
    assert record.state == STATE_ABORTED_PRE_EXECUTION


def test_recovery_hold_survives_restart(tmp_path):
    root = disposable_root(tmp_path)
    path = tmp_path / "lineage.sqlite3"
    store = RemoteMutationLineageStore(path)
    store.begin_attempt(
        transaction_id="tx-1",
        resource_id="repo:test",
        repository_root=root,
        authorization_id="authz-1",
        request_id="req-1",
        operation_id="repo.write_text_file",
        plan_sha256=A,
    )
    store.mark_recovery_hold("tx-1", reason="failure after execution intent")

    restarted = RemoteMutationLineageStore(path)
    latest = restarted.latest(resource_id="repo:test", repository_root=root)
    assert latest is not None
    assert latest.state == STATE_RECOVERY_HOLD


def test_tampered_lineage_row_fails_closed_on_read(tmp_path):
    root = disposable_root(tmp_path)
    path = tmp_path / "lineage.sqlite3"
    store = RemoteMutationLineageStore(path)
    store.begin_attempt(
        transaction_id="tx-1",
        resource_id="repo:test",
        repository_root=root,
        authorization_id="authz-1",
        request_id="req-1",
        operation_id="repo.write_text_file",
        plan_sha256=A,
    )
    store.mark_terminal("tx-1", closure())

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE remote_mutation_lineage SET evidence_sha256 = ? WHERE transaction_id = ?",
            ("c" * 64, "tx-1"),
        )

    with pytest.raises(MutationLineageError, match="integrity mismatch"):
        store.latest(resource_id="repo:test", repository_root=root)


def test_terminal_transition_rejects_mismatched_closure(tmp_path):
    root = disposable_root(tmp_path)
    store = RemoteMutationLineageStore(tmp_path / "lineage.sqlite3")
    store.begin_attempt(
        transaction_id="tx-1",
        resource_id="repo:test",
        repository_root=root,
        authorization_id="authz-1",
        request_id="req-1",
        operation_id="repo.write_text_file",
        plan_sha256=A,
    )

    with pytest.raises(MutationLineageError, match="does not match"):
        store.mark_terminal(
            "tx-1",
            closure(authorization_id="authz-other"),
        )

def test_aborted_attempt_does_not_hide_prior_terminal_lineage(tmp_path):
    root = disposable_root(tmp_path)
    store = RemoteMutationLineageStore(tmp_path / "lineage.sqlite3")

    store.begin_attempt(
        transaction_id="tx-terminal",
        resource_id="repo:test",
        repository_root=root,
        authorization_id="authz-terminal",
        request_id="req-terminal",
        operation_id="repo.write_text_file",
        plan_sha256=A,
    )
    store.mark_terminal(
        "tx-terminal",
        MutationExecutionClosureRecord(
            authorization_id="authz-terminal",
            authorization_sha256="c" * 64,
            evidence_sha256="d" * 64,
            executor_id="executor:test",
            execution_id="exec-terminal",
            transaction_id="tx-terminal",
            request_id="req-terminal",
            resource_id="repo:test",
            operation_id="repo.write_text_file",
            plan_sha256=A,
            closed=True,
            reason="terminal",
        ),
    )

    store.begin_attempt(
        transaction_id="tx-aborted",
        resource_id="repo:test",
        repository_root=root,
        authorization_id="authz-aborted",
        request_id="req-aborted",
        operation_id="repo.write_text_file",
        plan_sha256="e" * 64,
    )
    store.mark_aborted_pre_execution(
        "tx-aborted",
        reason="authorization expired before execution",
    )

    latest = store.latest(resource_id="repo:test", repository_root=root)
    assert latest is not None
    assert latest.transaction_id == "tx-terminal"
    assert latest.state == STATE_TERMINAL

