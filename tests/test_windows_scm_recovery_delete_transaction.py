import os

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_install_journal import (
    WindowsScmInstallJournalState,
    WindowsScmInstallationJournal,
)
from agent_control_plane.windows_scm_native_recovery_backend import (
    DELETE,
    SC_MANAGER_CONNECT,
    WindowsScmNativeRecoveryDeleteApi,
    WindowsScmNativeRecoveryDeleteBackend,
    probe_windows_scm_recovery_delete_api,
)
from agent_control_plane.windows_scm_recovery_authorization import (
    WindowsScmRecoveryAction,
    WindowsScmRecoveryAuthorizationStore,
    build_windows_scm_recovery_target,
)
from agent_control_plane.windows_scm_recovery_delete_transaction import (
    WindowsScmRecoveryDeleteTransaction,
    WindowsScmRecoveryDeleteTransactionError,
    WindowsScmRecoveryJournal,
    WindowsScmRecoveryJournalState,
)
from agent_control_plane.windows_scm_recovery_inspector import (
    WindowsScmInstallRecoveryInspector,
    WindowsScmLiveServiceConfig,
)
from agent_control_plane.windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)
from agent_control_plane.windows_scm_install_authorization import (
    WindowsScmInstallationTarget,
)


def plan():
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
        delayed_auto_start=False,
        desired_scm_access=3,
        desired_service_access=0x36,
    )


def install_target():
    return WindowsScmInstallationTarget(
        service_name="ACPAgentControlPlane",
        manifest_sha256="a" * 64,
        binary_sha256="b" * 64,
        registration_plan_sha256="c" * 64,
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


class Reader:
    def __init__(self, item):
        self.item = item
        self.calls = []

    def read(self, service_name):
        self.calls.append(service_name)
        return self.item


class Backend:
    def __init__(self, *, fail_delete=False, crash_delete=False):
        self.fail_delete = fail_delete
        self.crash_delete = crash_delete
        self.calls = []

    def open_scm(self):
        self.calls.append(("open_scm",))
        return "scm"

    def open_service_for_delete(self, scm_handle, service_name):
        self.calls.append(
            ("open_service_for_delete", scm_handle, service_name)
        )
        return "service"

    def delete_service(self, service_handle):
        self.calls.append(("delete_service", service_handle))
        if self.crash_delete:
            raise SystemExit(17)
        if self.fail_delete:
            raise RuntimeError("delete failed")

    def close_handle(self, handle):
        self.calls.append(("close_handle", handle))


def prepare_install_journal(tmp_path):
    journal = WindowsScmInstallationJournal(
        tmp_path / "install-journal.sqlite3"
    )
    journal.begin(
        transaction_id="install-tx-1",
        authorization_id="install-auth-1",
        target=install_target(),
        created_at="2026-09-26T10:00:00Z",
    )
    for state in (
        WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
        WindowsScmInstallJournalState.SCM_OPENED,
        WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
        WindowsScmInstallJournalState.SERVICE_CREATED,
    ):
        journal.append(
            "install-tx-1",
            state=state,
            occurred_at="2026-09-26T10:01:00Z",
        )
    return journal


def issue_recovery_authorization(tmp_path, install_journal, reader):
    inspector = WindowsScmInstallRecoveryInspector(reader)
    record = install_journal.get("install-tx-1")
    assessment = install_journal.assess_recovery("install-tx-1")
    inspection = inspector.inspect(
        assessment=assessment,
        plan=plan(),
    )
    target = build_windows_scm_recovery_target(
        journal_record=record,
        assessment=assessment,
        inspection=inspection,
        action=WindowsScmRecoveryAction.DELETE_EXACT_SERVICE,
    )
    store = WindowsScmRecoveryAuthorizationStore(
        tmp_path / "recovery-auth.sqlite3"
    )
    store.issue(
        authorization_id="recovery-auth-1",
        target=target,
        authorized_by="operator-a",
        issued_at="2026-09-26T10:02:00Z",
        expires_at="2026-09-26T10:12:00Z",
    )
    return store, inspector


def test_authorized_recovery_delete_is_reinspected_and_journaled(tmp_path):
    install_journal = prepare_install_journal(tmp_path)
    reader = Reader(live())
    auth_store, inspector = issue_recovery_authorization(
        tmp_path,
        install_journal,
        reader,
    )
    recovery_journal = WindowsScmRecoveryJournal(
        tmp_path / "recovery-journal.sqlite3"
    )
    backend = Backend()
    tx = WindowsScmRecoveryDeleteTransaction(
        install_journal=install_journal,
        recovery_journal=recovery_journal,
        authorization_store=auth_store,
        inspector=inspector,
        backend=backend,
    )

    result = tx.delete(
        recovery_transaction_id="recovery-tx-1",
        authorization_id="recovery-auth-1",
        install_transaction_id="install-tx-1",
        plan=plan(),
        now="2026-09-26T10:05:00Z",
    )

    assert result.deleted is True
    assert reader.calls == [
        "ACPAgentControlPlane",
        "ACPAgentControlPlane",
    ]
    assert auth_store.get("recovery-auth-1").consumed_at is not None
    record = recovery_journal.get("recovery-tx-1")
    assert tuple(event.state for event in record.events) == (
        WindowsScmRecoveryJournalState.PREPARED,
        WindowsScmRecoveryJournalState.AUTHORIZATION_CONSUMED,
        WindowsScmRecoveryJournalState.DELETE_INTENT_RECORDED,
        WindowsScmRecoveryJournalState.DELETED,
    )
    assert backend.calls == [
        ("open_scm",),
        (
            "open_service_for_delete",
            "scm",
            "ACPAgentControlPlane",
        ),
        ("delete_service", "service"),
        ("close_handle", "service"),
        ("close_handle", "scm"),
    ]


def test_live_config_drift_fails_before_auth_consumption_or_backend(tmp_path):
    install_journal = prepare_install_journal(tmp_path)
    reader = Reader(live())
    auth_store, inspector = issue_recovery_authorization(
        tmp_path,
        install_journal,
        reader,
    )
    reader.item = live(display_name="Changed after authorization")
    backend = Backend()
    recovery_journal = WindowsScmRecoveryJournal(
        tmp_path / "recovery-journal.sqlite3"
    )
    tx = WindowsScmRecoveryDeleteTransaction(
        install_journal=install_journal,
        recovery_journal=recovery_journal,
        authorization_store=auth_store,
        inspector=inspector,
        backend=backend,
    )

    with pytest.raises(AuthorityValidationError):
        tx.delete(
            recovery_transaction_id="recovery-tx-1",
            authorization_id="recovery-auth-1",
            install_transaction_id="install-tx-1",
            plan=plan(),
            now="2026-09-26T10:05:00Z",
        )

    assert auth_store.get("recovery-auth-1").consumed_at is None
    assert recovery_journal.get("recovery-tx-1") is None
    assert backend.calls == []


def test_explicit_delete_failure_is_terminally_journaled(tmp_path):
    install_journal = prepare_install_journal(tmp_path)
    auth_store, inspector = issue_recovery_authorization(
        tmp_path,
        install_journal,
        Reader(live()),
    )
    recovery_journal = WindowsScmRecoveryJournal(
        tmp_path / "recovery-journal.sqlite3"
    )
    tx = WindowsScmRecoveryDeleteTransaction(
        install_journal=install_journal,
        recovery_journal=recovery_journal,
        authorization_store=auth_store,
        inspector=inspector,
        backend=Backend(fail_delete=True),
    )

    with pytest.raises(
        WindowsScmRecoveryDeleteTransactionError,
        match="delete failed",
    ):
        tx.delete(
            recovery_transaction_id="recovery-tx-1",
            authorization_id="recovery-auth-1",
            install_transaction_id="install-tx-1",
            plan=plan(),
            now="2026-09-26T10:05:00Z",
        )

    record = recovery_journal.get("recovery-tx-1")
    assert record.current_state is WindowsScmRecoveryJournalState.DELETE_FAILED
    assert "RuntimeError: delete failed" == record.events[-1].error


def test_abrupt_process_death_leaves_delete_intent_ambiguous(tmp_path):
    install_journal = prepare_install_journal(tmp_path)
    auth_store, inspector = issue_recovery_authorization(
        tmp_path,
        install_journal,
        Reader(live()),
    )
    recovery_journal = WindowsScmRecoveryJournal(
        tmp_path / "recovery-journal.sqlite3"
    )
    backend = Backend(crash_delete=True)
    tx = WindowsScmRecoveryDeleteTransaction(
        install_journal=install_journal,
        recovery_journal=recovery_journal,
        authorization_store=auth_store,
        inspector=inspector,
        backend=backend,
    )

    with pytest.raises(SystemExit):
        tx.delete(
            recovery_transaction_id="recovery-tx-1",
            authorization_id="recovery-auth-1",
            install_transaction_id="install-tx-1",
            plan=plan(),
            now="2026-09-26T10:05:00Z",
        )

    record = recovery_journal.get("recovery-tx-1")
    assert (
        record.current_state
        is WindowsScmRecoveryJournalState.DELETE_INTENT_RECORDED
    )
    assert auth_store.get("recovery-auth-1").consumed_at is not None
    assert backend.calls[-2:] == [
        ("close_handle", "service"),
        ("close_handle", "scm"),
    ]


def test_consumed_recovery_authorization_cannot_be_replayed(tmp_path):
    install_journal = prepare_install_journal(tmp_path)
    auth_store, inspector = issue_recovery_authorization(
        tmp_path,
        install_journal,
        Reader(live()),
    )
    backend = Backend()
    tx = WindowsScmRecoveryDeleteTransaction(
        install_journal=install_journal,
        recovery_journal=WindowsScmRecoveryJournal(
            tmp_path / "recovery-journal.sqlite3"
        ),
        authorization_store=auth_store,
        inspector=inspector,
        backend=backend,
    )
    tx.delete(
        recovery_transaction_id="recovery-tx-1",
        authorization_id="recovery-auth-1",
        install_transaction_id="install-tx-1",
        plan=plan(),
        now="2026-09-26T10:05:00Z",
    )

    second_backend = Backend()
    second = WindowsScmRecoveryDeleteTransaction(
        install_journal=install_journal,
        recovery_journal=WindowsScmRecoveryJournal(
            tmp_path / "recovery-journal-2.sqlite3"
        ),
        authorization_store=auth_store,
        inspector=inspector,
        backend=second_backend,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="already consumed",
    ):
        second.delete(
            recovery_transaction_id="recovery-tx-2",
            authorization_id="recovery-auth-1",
            install_transaction_id="install-tx-1",
            plan=plan(),
            now="2026-09-26T10:06:00Z",
        )
    assert second_backend.calls == []


class FakeNativeApi:
    def __init__(self):
        self.calls = []

    def open_scm(self, machine, database, access):
        self.calls.append(("open_scm", machine, database, access))
        return 101

    def open_service(self, scm, name, access):
        self.calls.append(("open_service", scm, name, access))
        return 202

    def delete_service(self, handle):
        self.calls.append(("delete_service", handle))
        return True

    def close_service_handle(self, handle):
        self.calls.append(("close", handle))
        return True


def test_native_delete_backend_requests_only_connect_and_delete_access():
    api = FakeNativeApi()
    backend = WindowsScmNativeRecoveryDeleteBackend(api=api)

    scm = backend.open_scm()
    service = backend.open_service_for_delete(
        scm,
        "ACPAgentControlPlane",
    )
    backend.delete_service(service)
    backend.close_handle(service)
    backend.close_handle(scm)

    assert api.calls == [
        ("open_scm", None, None, SC_MANAGER_CONNECT),
        ("open_service", 101, "ACPAgentControlPlane", DELETE),
        ("delete_service", 202),
        ("close", 202),
        ("close", 101),
    ]


def test_recovery_delete_probe_is_explicit_off_windows():
    probe = probe_windows_scm_recovery_delete_api()
    if os.name == "nt":
        assert probe.is_windows is True
    else:
        assert probe.is_windows is False
        assert probe.available is False


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native recovery delete API")
def test_windows_recovery_delete_exports_load():
    probe = probe_windows_scm_recovery_delete_api()
    assert probe.available is True
    api = WindowsScmNativeRecoveryDeleteApi()
    assert api.open_scm.restype is not None
    assert api.open_service.restype is not None
    assert api.delete_service.restype is not None
    assert api.close_service_handle.restype is not None
