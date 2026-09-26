import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_install_authorization import (
    WindowsScmInstallationAuthorizationStore,
    WindowsScmInstallationTarget,
    windows_scm_registration_plan_sha256,
)
from agent_control_plane.windows_scm_install_journal import (
    DurableWindowsScmInstallJournal,
    WindowsScmInstallJournalEvent,
    WindowsScmInstallRecoveryState,
)
from agent_control_plane.windows_scm_install_transaction import (
    WindowsScmInstallationTransactionError,
    WindowsScmServiceInstallationTransaction,
)
from agent_control_plane.windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)


def plan(*, delayed_auto_start=False):
    return WindowsScmServiceRegistrationPlan(
        manifest_sha256="a" * 64,
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path_command=r'"c:\acp\acp-supervisor.exe"',
        service_type=0x10,
        start_type=3,
        error_control=1,
        dependencies_multi_sz=None,
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        credential_reference=None,
        requires_credential_resolution=False,
        delayed_auto_start=delayed_auto_start,
        desired_scm_access=3,
        desired_service_access=0x36,
    )


def target_for(item):
    return WindowsScmInstallationTarget(
        service_name=item.service_name,
        manifest_sha256=item.manifest_sha256,
        binary_sha256="b" * 64,
        registration_plan_sha256=windows_scm_registration_plan_sha256(item),
    )


class Backend:
    def __init__(self, *, fail_config=False, fail_delete=False):
        self.fail_config = fail_config
        self.fail_delete = fail_delete

    def open_scm(self, desired_access):
        return "scm"

    def create_service(self, scm_handle, plan, credential_secret):
        return "service"

    def configure_delayed_auto_start(self, service_handle, enabled):
        if self.fail_config:
            raise RuntimeError("config failed")

    def delete_service(self, service_handle):
        if self.fail_delete:
            raise RuntimeError("delete failed")

    def close_handle(self, handle):
        pass


def issue(store, target):
    store.issue(
        authorization_id="install-1",
        target=target,
        authorized_by="operator-test",
        issued_at="2026-09-26T10:00:00Z",
        expires_at="2026-09-26T11:00:00Z",
    )


def test_successful_transaction_journal_reaches_committed(tmp_path):
    item = plan()
    target = target_for(item)
    auth = WindowsScmInstallationAuthorizationStore(tmp_path / "auth.sqlite3")
    journal = DurableWindowsScmInstallJournal(tmp_path / "journal.sqlite3")
    issue(auth, target)

    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=auth,
        backend=Backend(),
        journal=journal,
    )
    tx.install(
        authorization_id="install-1",
        target=target,
        plan=item,
        now="2026-09-26T10:05:00Z",
    )

    events = tuple(r.event for r in journal.records("install-1"))
    assert events == (
        WindowsScmInstallJournalEvent.AUTHORIZATION_CONSUMED,
        WindowsScmInstallJournalEvent.SCM_OPEN_INTENT,
        WindowsScmInstallJournalEvent.SCM_OPENED,
        WindowsScmInstallJournalEvent.CREATE_SERVICE_INTENT,
        WindowsScmInstallJournalEvent.SERVICE_CREATED,
        WindowsScmInstallJournalEvent.INSTALL_COMMITTED,
    )
    assert (
        journal.recovery_state("install-1")
        is WindowsScmInstallRecoveryState.COMMITTED
    )


def test_post_create_failure_journals_completed_rollback(tmp_path):
    item = plan(delayed_auto_start=True)
    target = target_for(item)
    auth = WindowsScmInstallationAuthorizationStore(tmp_path / "auth.sqlite3")
    journal = DurableWindowsScmInstallJournal(tmp_path / "journal.sqlite3")
    issue(auth, target)

    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=auth,
        backend=Backend(fail_config=True),
        journal=journal,
    )
    with pytest.raises(WindowsScmInstallationTransactionError):
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T10:05:00Z",
        )

    assert (
        journal.recovery_state("install-1")
        is WindowsScmInstallRecoveryState.ROLLED_BACK
    )


def test_create_intent_without_completion_is_ambiguous(tmp_path):
    target = target_for(plan())
    journal = DurableWindowsScmInstallJournal(tmp_path / "journal.sqlite3")

    for event in (
        WindowsScmInstallJournalEvent.AUTHORIZATION_CONSUMED,
        WindowsScmInstallJournalEvent.SCM_OPEN_INTENT,
        WindowsScmInstallJournalEvent.SCM_OPENED,
        WindowsScmInstallJournalEvent.CREATE_SERVICE_INTENT,
    ):
        journal.append(
            authorization_id="install-1",
            target=target,
            event=event,
            recorded_at="2026-09-26T10:05:00Z",
        )

    assert (
        journal.recovery_state("install-1")
        is WindowsScmInstallRecoveryState.CREATE_OUTCOME_AMBIGUOUS
    )


def test_created_without_commit_requires_recovery(tmp_path):
    target = target_for(plan())
    journal = DurableWindowsScmInstallJournal(tmp_path / "journal.sqlite3")
    for event in (
        WindowsScmInstallJournalEvent.CREATE_SERVICE_INTENT,
        WindowsScmInstallJournalEvent.SERVICE_CREATED,
    ):
        journal.append(
            authorization_id="install-1",
            target=target,
            event=event,
            recorded_at="2026-09-26T10:05:00Z",
        )
    assert (
        journal.recovery_state("install-1")
        is WindowsScmInstallRecoveryState.SERVICE_EXISTS_UNCOMMITTED
    )


def test_rollback_intent_without_completion_is_ambiguous(tmp_path):
    target = target_for(plan())
    journal = DurableWindowsScmInstallJournal(tmp_path / "journal.sqlite3")
    for event in (
        WindowsScmInstallJournalEvent.SERVICE_CREATED,
        WindowsScmInstallJournalEvent.ROLLBACK_DELETE_INTENT,
    ):
        journal.append(
            authorization_id="install-1",
            target=target,
            event=event,
            recorded_at="2026-09-26T10:05:00Z",
        )
    assert (
        journal.recovery_state("install-1")
        is WindowsScmInstallRecoveryState.ROLLBACK_OUTCOME_AMBIGUOUS
    )


def test_journal_target_drift_fails_closed(tmp_path):
    journal = DurableWindowsScmInstallJournal(tmp_path / "journal.sqlite3")
    first = target_for(plan())
    journal.append(
        authorization_id="install-1",
        target=first,
        event=WindowsScmInstallJournalEvent.AUTHORIZATION_CONSUMED,
        recorded_at="2026-09-26T10:05:00Z",
    )
    drifted = WindowsScmInstallationTarget(
        service_name=first.service_name,
        manifest_sha256="c" * 64,
        binary_sha256=first.binary_sha256,
        registration_plan_sha256=first.registration_plan_sha256,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="target conflict",
    ):
        journal.append(
            authorization_id="install-1",
            target=drifted,
            event=WindowsScmInstallJournalEvent.SCM_OPEN_INTENT,
            recorded_at="2026-09-26T10:05:01Z",
        )


def test_journal_survives_reopen(tmp_path):
    path = tmp_path / "journal.sqlite3"
    target = target_for(plan())
    first = DurableWindowsScmInstallJournal(path)
    first.append(
        authorization_id="install-1",
        target=target,
        event=WindowsScmInstallJournalEvent.CREATE_SERVICE_INTENT,
        recorded_at="2026-09-26T10:05:00Z",
    )

    reopened = DurableWindowsScmInstallJournal(path)
    assert len(reopened.records("install-1")) == 1
    assert (
        reopened.recovery_state("install-1")
        is WindowsScmInstallRecoveryState.CREATE_OUTCOME_AMBIGUOUS
    )
