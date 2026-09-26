import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.supervisor_recovery_authorization import (
    SupervisorRecoveryAuthorizationStore,
    supervisor_checkpoint_sha256,
)
from agent_control_plane.supervisor_runtime_checkpoint import (
    SupervisorPreviousRunDisposition,
    SupervisorRecoveryAssessment,
    SupervisorRuntimeCheckpoint,
)
from agent_control_plane.supervisor_service import SupervisorServiceState


def assessment(
    *,
    generation=4,
    fence=9,
    disposition=SupervisorPreviousRunDisposition.UNCLEAN_EXIT,
):
    previous = SupervisorRuntimeCheckpoint(
        service_id="acp-supervisor",
        generation=generation,
        owner_id="previous-owner",
        fencing_token=fence,
        state=SupervisorServiceState.RUNNING,
        stop_reason=None,
        updated_at="2026-09-25T22:00:00Z",
    )
    return SupervisorRecoveryAssessment(
        disposition=disposition,
        previous=previous,
        stale_owner=True,
    )


def test_exact_authorization_can_be_consumed_once(tmp_path):
    store = SupervisorRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    current = assessment()
    issued = store.issue(
        authorization_id="auth-1",
        assessment=current,
        authorized_by="operator-1",
        issued_at="2026-09-25T22:10:00Z",
        expires_at="2026-09-25T22:20:00Z",
    )
    assert issued.previous_checkpoint_sha256 == (
        supervisor_checkpoint_sha256(current.previous)
    )

    consumed = store.consume(
        "auth-1",
        assessment=current,
        now="2026-09-25T22:11:00Z",
    )
    assert consumed.consumed_at == "2026-09-25T22:11:00Z"

    with pytest.raises(
        AuthorityValidationError,
        match="already consumed",
    ):
        store.consume(
            "auth-1",
            assessment=current,
            now="2026-09-25T22:12:00Z",
        )


def test_stale_generation_authorization_is_rejected(tmp_path):
    store = SupervisorRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    old = assessment(generation=4)
    store.issue(
        authorization_id="auth-1",
        assessment=old,
        authorized_by="operator-1",
        issued_at="2026-09-25T22:10:00Z",
        expires_at="2026-09-25T22:20:00Z",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="does not match",
    ):
        store.consume(
            "auth-1",
            assessment=assessment(generation=5),
            now="2026-09-25T22:11:00Z",
        )


def test_wrong_fence_or_disposition_is_rejected(tmp_path):
    store = SupervisorRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    old = assessment()
    store.issue(
        authorization_id="auth-1",
        assessment=old,
        authorized_by="operator-1",
        issued_at="2026-09-25T22:10:00Z",
        expires_at="2026-09-25T22:20:00Z",
    )

    with pytest.raises(
        AuthorityValidationError,
        match="does not match",
    ):
        store.consume(
            "auth-1",
            assessment=assessment(fence=10),
            now="2026-09-25T22:11:00Z",
        )

    with pytest.raises(
        AuthorityValidationError,
        match="does not match",
    ):
        store.consume(
            "auth-1",
            assessment=assessment(
                disposition=SupervisorPreviousRunDisposition.PRIOR_FAILURE
            ),
            now="2026-09-25T22:11:00Z",
        )


def test_expired_authorization_is_rejected(tmp_path):
    store = SupervisorRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    current = assessment()
    store.issue(
        authorization_id="auth-1",
        assessment=current,
        authorized_by="operator-1",
        issued_at="2026-09-25T22:10:00Z",
        expires_at="2026-09-25T22:20:00Z",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="expired",
    ):
        store.consume(
            "auth-1",
            assessment=current,
            now="2026-09-25T22:20:00Z",
        )


def test_terminal_give_up_requires_separate_explicit_enable(tmp_path):
    store = SupervisorRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    current = assessment(
        disposition=SupervisorPreviousRunDisposition.TERMINAL_GIVE_UP
    )
    store.issue(
        authorization_id="auth-give-up",
        assessment=current,
        authorized_by="operator-1",
        issued_at="2026-09-25T22:10:00Z",
        expires_at="2026-09-25T22:20:00Z",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="disabled",
    ):
        store.consume(
            "auth-give-up",
            assessment=current,
            now="2026-09-25T22:11:00Z",
        )
    assert store.get("auth-give-up").consumed_at is None

    consumed = store.consume(
        "auth-give-up",
        assessment=current,
        now="2026-09-25T22:12:00Z",
        allow_terminal_give_up=True,
    )
    assert consumed.consumed_at == "2026-09-25T22:12:00Z"


def test_clean_recovery_does_not_accept_authorization_issue(tmp_path):
    store = SupervisorRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    current = assessment(
        disposition=SupervisorPreviousRunDisposition.CLEAN_STOP
    )
    with pytest.raises(
        AuthorityValidationError,
        match="unnecessary",
    ):
        store.issue(
            authorization_id="auth-clean",
            assessment=current,
            authorized_by="operator-1",
            issued_at="2026-09-25T22:10:00Z",
            expires_at="2026-09-25T22:20:00Z",
        )


def test_manifest_contains_exact_binding_and_consumption_state(tmp_path):
    store = SupervisorRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    current = assessment()
    store.issue(
        authorization_id="auth-1",
        assessment=current,
        authorized_by="operator-1",
        issued_at="2026-09-25T22:10:00Z",
        expires_at="2026-09-25T22:20:00Z",
    )
    manifest = store.manifest()
    assert manifest["authorization_count"] == 1
    record = manifest["authorizations"][0]
    assert record["previous_generation"] == 4
    assert record["previous_fencing_token"] == 9
    assert record["consumed_at"] is None
