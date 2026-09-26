import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_install_journal import (
    WindowsScmInstallJournalEvent,
    WindowsScmInstallJournalRecord,
    WindowsScmInstallJournalState,
    WindowsScmInstallRecoveryAssessment,
    WindowsScmInstallRecoveryDisposition,
)
from agent_control_plane.windows_scm_recovery_authorization import (
    WindowsScmRecoveryAction,
    WindowsScmRecoveryAuthorizationStore,
    build_windows_scm_recovery_target,
    windows_scm_live_config_sha256,
)
from agent_control_plane.windows_scm_recovery_inspector import (
    WindowsScmInstallRecoveryInspection,
    WindowsScmLiveServiceConfig,
    WindowsScmRecoveryResolution,
)


def record():
    event = WindowsScmInstallJournalEvent(
        transaction_id="tx-1",
        event_index=4,
        state=WindowsScmInstallJournalState.SERVICE_CREATED,
        occurred_at="2026-09-26T10:00:00Z",
        error=None,
    )
    return WindowsScmInstallJournalRecord(
        transaction_id="tx-1",
        authorization_id="install-auth-1",
        service_name="ACPAgentControlPlane",
        manifest_sha256="a" * 64,
        binary_sha256="b" * 64,
        registration_plan_sha256="c" * 64,
        created_at="2026-09-26T09:59:00Z",
        events=(event,),
    )


def assessment(
    disposition=(
        WindowsScmInstallRecoveryDisposition.HOLD_POSSIBLE_INSTALLED_SERVICE
    ),
):
    return WindowsScmInstallRecoveryAssessment(
        transaction_id="tx-1",
        current_state=WindowsScmInstallJournalState.SERVICE_CREATED,
        disposition=disposition,
        service_mutation_may_exist=True,
    )


def live(**changes):
    values = dict(
        service_name="ACPAgentControlPlane",
        service_type=0x10,
        start_type=3,
        error_control=1,
        binary_path_command=r'"c:\acp\acp-supervisor.exe"',
        dependencies=(),
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        delayed_auto_start=False,
    )
    values.update(changes)
    return WindowsScmLiveServiceConfig(**values)


def inspection(
    resolution=WindowsScmRecoveryResolution.INSTALLED_MATCH,
    *,
    live_service=None,
    disposition=(
        WindowsScmInstallRecoveryDisposition.HOLD_POSSIBLE_INSTALLED_SERVICE
    ),
):
    return WindowsScmInstallRecoveryInspection(
        journal_disposition=disposition,
        resolution=resolution,
        live_service=(
            live() if live_service is None and resolution
            is WindowsScmRecoveryResolution.INSTALLED_MATCH
            else live_service
        ),
    )


def target():
    return build_windows_scm_recovery_target(
        journal_record=record(),
        assessment=assessment(),
        inspection=inspection(),
        action=WindowsScmRecoveryAction.DELETE_EXACT_SERVICE,
    )


def test_target_binds_transaction_hashes_and_live_config():
    item = target()

    assert item.transaction_id == "tx-1"
    assert item.service_name == "ACPAgentControlPlane"
    assert item.manifest_sha256 == "a" * 64
    assert item.binary_sha256 == "b" * 64
    assert item.registration_plan_sha256 == "c" * 64
    assert item.live_config_sha256 == windows_scm_live_config_sha256(live())
    assert item.action is WindowsScmRecoveryAction.DELETE_EXACT_SERVICE


def test_absent_or_mismatched_service_cannot_authorize_delete():
    for resolution in (
        WindowsScmRecoveryResolution.SERVICE_ABSENT,
        WindowsScmRecoveryResolution.HOLD_LIVE_CONFIG_MISMATCH,
        WindowsScmRecoveryResolution.HOLD_LIVE_QUERY_ERROR,
    ):
        with pytest.raises(
            AuthorityValidationError,
            match="exact installed-match inspection required",
        ):
            build_windows_scm_recovery_target(
                journal_record=record(),
                assessment=assessment(),
                inspection=inspection(
                    resolution,
                    live_service=(
                        live(display_name="Other")
                        if resolution is WindowsScmRecoveryResolution.HOLD_LIVE_CONFIG_MISMATCH
                        else None
                    ),
                ),
                action=WindowsScmRecoveryAction.DELETE_EXACT_SERVICE,
            )


def test_clean_journal_state_cannot_authorize_recovery_delete():
    clean = assessment(
        WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED
    )
    clean_inspection = inspection(
        disposition=WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="does not permit recovery deletion",
    ):
        build_windows_scm_recovery_target(
            journal_record=record(),
            assessment=clean,
            inspection=clean_inspection,
            action=WindowsScmRecoveryAction.DELETE_EXACT_SERVICE,
        )


def test_disposition_mismatch_fails_closed():
    with pytest.raises(
        AuthorityValidationError,
        match="inspection disposition mismatch",
    ):
        build_windows_scm_recovery_target(
            journal_record=record(),
            assessment=assessment(),
            inspection=inspection(
                disposition=(
                    WindowsScmInstallRecoveryDisposition.HOLD_ROLLBACK_FAILED
                )
            ),
            action=WindowsScmRecoveryAction.DELETE_EXACT_SERVICE,
        )


def test_issue_consume_is_exact_expiring_and_single_use(tmp_path):
    store = WindowsScmRecoveryAuthorizationStore(
        tmp_path / "recovery.sqlite3"
    )
    item = target()
    issued = store.issue(
        authorization_id="recovery-1",
        target=item,
        authorized_by="operator-a",
        issued_at="2026-09-26T10:00:00Z",
        expires_at="2026-09-26T10:10:00Z",
    )
    assert issued.consumed_at is None

    consumed = store.consume(
        "recovery-1",
        target=item,
        now="2026-09-26T10:05:00Z",
    )
    assert consumed.consumed_at == "2026-09-26T10:05:00Z"

    with pytest.raises(
        AuthorityValidationError,
        match="already consumed",
    ):
        store.consume(
            "recovery-1",
            target=item,
            now="2026-09-26T10:06:00Z",
        )


def test_expired_authorization_fails_closed(tmp_path):
    store = WindowsScmRecoveryAuthorizationStore(
        tmp_path / "recovery.sqlite3"
    )
    item = target()
    store.issue(
        authorization_id="recovery-1",
        target=item,
        authorized_by="operator-a",
        issued_at="2026-09-26T10:00:00Z",
        expires_at="2026-09-26T10:10:00Z",
    )

    with pytest.raises(
        AuthorityValidationError,
        match="expired",
    ):
        store.consume(
            "recovery-1",
            target=item,
            now="2026-09-26T10:10:00Z",
        )


def test_live_config_drift_invalidates_authorization(tmp_path):
    store = WindowsScmRecoveryAuthorizationStore(
        tmp_path / "recovery.sqlite3"
    )
    original = target()
    store.issue(
        authorization_id="recovery-1",
        target=original,
        authorized_by="operator-a",
        issued_at="2026-09-26T10:00:00Z",
        expires_at="2026-09-26T10:10:00Z",
    )

    changed_inspection = inspection(
        live_service=live(display_name="Changed")
    )
    changed = build_windows_scm_recovery_target(
        journal_record=record(),
        assessment=assessment(),
        inspection=changed_inspection,
        action=WindowsScmRecoveryAction.DELETE_EXACT_SERVICE,
    )

    with pytest.raises(
        AuthorityValidationError,
        match="does not match target",
    ):
        store.consume(
            "recovery-1",
            target=changed,
            now="2026-09-26T10:05:00Z",
        )
    assert store.get("recovery-1").consumed_at is None


def test_issue_rejects_invalid_expiry(tmp_path):
    store = WindowsScmRecoveryAuthorizationStore(
        tmp_path / "recovery.sqlite3"
    )
    with pytest.raises(
        AuthorityValidationError,
        match="after issued_at",
    ):
        store.issue(
            authorization_id="recovery-1",
            target=target(),
            authorized_by="operator-a",
            issued_at="2026-09-26T10:00:00Z",
            expires_at="2026-09-26T10:00:00Z",
        )
