import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_install_authorization import (
    WindowsScmInstallationAuthorizationStore,
    WindowsScmInstallationTarget,
    windows_scm_registration_plan_sha256,
)
from agent_control_plane.windows_scm_install_transaction import (
    WindowsScmInstallationTransactionError,
    WindowsScmServiceInstallationTransaction,
)
from agent_control_plane.windows_scm_install_journal import (
    WindowsScmInstallationJournal,
    WindowsScmInstallJournalState,
    WindowsScmInstallRecoveryDisposition,
)
from agent_control_plane.windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)


def plan(
    *,
    credential_reference=None,
    requires_credential_resolution=False,
    delayed_auto_start=False,
):
    return WindowsScmServiceRegistrationPlan(
        manifest_sha256="a" * 64,
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path_command=r'"c:\acp\acp-supervisor.exe"',
        service_type=0x10,
        start_type=3,
        error_control=1,
        dependencies_multi_sz=None,
        account_name=(
            r".\acp-service-user"
            if requires_credential_resolution
            else r"NT SERVICE\ACPAgentControlPlane"
        ),
        credential_reference=credential_reference,
        requires_credential_resolution=requires_credential_resolution,
        delayed_auto_start=delayed_auto_start,
        desired_scm_access=3,
        desired_service_access=0x36,
    )


def target_for(item):
    return WindowsScmInstallationTarget(
        service_name=item.service_name,
        manifest_sha256=item.manifest_sha256,
        binary_sha256="b" * 64,
        registration_plan_sha256=windows_scm_registration_plan_sha256(
            item
        ),
    )


def issue(store, target, authorization_id="install-1"):
    return store.issue(
        authorization_id=authorization_id,
        target=target,
        authorized_by="operator-a",
        issued_at="2026-09-26T09:00:00Z",
        expires_at="2026-09-26T10:00:00Z",
    )


class FakeBackend:
    def __init__(
        self,
        *,
        store=None,
        authorization_id=None,
        fail_create=False,
        fail_config=False,
        fail_delete=False,
    ):
        self.store = store
        self.authorization_id = authorization_id
        self.fail_create = fail_create
        self.fail_config = fail_config
        self.fail_delete = fail_delete
        self.calls = []
        self.received_secret = None

    def open_scm(self, desired_access):
        if self.store is not None:
            record = self.store.get(self.authorization_id)
            assert record is not None
            assert record.consumed_at is not None
        self.calls.append(("open_scm", desired_access))
        return "scm-handle"

    def create_service(self, scm_handle, plan, credential_secret):
        self.calls.append(("create_service", scm_handle, plan.service_name))
        self.received_secret = credential_secret
        if self.fail_create:
            raise RuntimeError("create failed")
        return "service-handle"

    def configure_delayed_auto_start(self, service_handle, enabled):
        self.calls.append(("configure_delayed", service_handle, enabled))
        if self.fail_config:
            raise RuntimeError("config failed")

    def delete_service(self, service_handle):
        self.calls.append(("delete_service", service_handle))
        if self.fail_delete:
            raise RuntimeError("delete failed")

    def close_handle(self, handle):
        self.calls.append(("close_handle", handle))


def test_authorization_is_consumed_before_backend_open(tmp_path):
    item = plan()
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    backend = FakeBackend(
        store=store,
        authorization_id="install-1",
    )
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
    )

    result = tx.install(
        authorization_id="install-1",
        target=target,
        plan=item,
        now="2026-09-26T09:05:00Z",
    )

    assert result.mutation_steps == (
        "authorization_consumed",
        "scm_opened",
        "service_created",
    )
    assert backend.calls[-2:] == [
        ("close_handle", "service-handle"),
        ("close_handle", "scm-handle"),
    ]


def test_credential_secret_is_resolved_only_for_required_plan(tmp_path):
    item = plan(
        credential_reference="vault:acp-service",
        requires_credential_resolution=True,
    )
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    backend = FakeBackend()
    seen = []

    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
        credential_resolver=lambda ref: (
            seen.append(ref) or "super-secret"
        ),
    )
    result = tx.install(
        authorization_id="install-1",
        target=target,
        plan=item,
        now="2026-09-26T09:05:00Z",
    )

    assert seen == ["vault:acp-service"]
    assert backend.received_secret == "super-secret"
    assert not hasattr(result, "credential_secret")
    assert "super-secret" not in repr(result)


def test_missing_credential_resolver_fails_before_authorization_consumption(
    tmp_path,
):
    item = plan(
        credential_reference="vault:acp-service",
        requires_credential_resolution=True,
    )
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    backend = FakeBackend()
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
    )

    with pytest.raises(
        AuthorityValidationError,
        match="credential resolver required",
    ):
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
        )

    assert store.get("install-1").consumed_at is None
    assert backend.calls == []


def test_create_failure_consumes_authorization_and_closes_scm_handle(tmp_path):
    item = plan()
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    backend = FakeBackend(fail_create=True)
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
    )

    with pytest.raises(
        WindowsScmInstallationTransactionError,
        match="create failed",
    ) as exc:
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
        )

    assert store.get("install-1").consumed_at is not None
    assert exc.value.rollback_performed is False
    assert ("close_handle", "scm-handle") in backend.calls
    assert not any(call[0] == "delete_service" for call in backend.calls)


def test_post_create_failure_rolls_back_and_closes_handles(tmp_path):
    item = plan(delayed_auto_start=True)
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    backend = FakeBackend(fail_config=True)
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
    )

    with pytest.raises(
        WindowsScmInstallationTransactionError,
        match="config failed",
    ) as exc:
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
        )

    assert exc.value.rollback_performed is True
    assert exc.value.rollback_error is None
    assert ("delete_service", "service-handle") in backend.calls
    assert backend.calls[-2:] == [
        ("close_handle", "service-handle"),
        ("close_handle", "scm-handle"),
    ]


def test_rollback_failure_is_reported_not_hidden(tmp_path):
    item = plan(delayed_auto_start=True)
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    backend = FakeBackend(fail_config=True, fail_delete=True)
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
    )

    with pytest.raises(WindowsScmInstallationTransactionError) as exc:
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
        )

    assert exc.value.rollback_performed is False
    assert exc.value.rollback_error == "RuntimeError: delete failed"
    assert "service_delete_rollback_failed" in exc.value.mutation_steps


def test_reusing_consumed_authorization_fails_before_second_backend_call(
    tmp_path,
):
    item = plan()
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    first_backend = FakeBackend()
    first = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=first_backend,
    )
    first.install(
        authorization_id="install-1",
        target=target,
        plan=item,
        now="2026-09-26T09:05:00Z",
    )

    second_backend = FakeBackend()
    second = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=second_backend,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="already consumed",
    ):
        second.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:06:00Z",
        )
    assert second_backend.calls == []


def test_plan_drift_fails_before_authorization_or_backend(tmp_path):
    item = plan()
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    changed = WindowsScmServiceRegistrationPlan(
        **{
            **item.__dict__,
            "display_name": "Changed Display",
        }
    )
    backend = FakeBackend()
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
    )

    with pytest.raises(
        AuthorityValidationError,
        match="plan identity does not match target",
    ):
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=changed,
            now="2026-09-26T09:05:00Z",
        )

    assert store.get("install-1").consumed_at is None
    assert backend.calls == []



def test_success_is_durably_journaled_to_completed(tmp_path):
    item = plan()
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    journal = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    )
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=FakeBackend(),
        journal=journal,
    )

    tx.install(
        authorization_id="install-1",
        target=target,
        plan=item,
        now="2026-09-26T09:05:00Z",
        transaction_id="tx-success",
    )

    record = journal.get("tx-success")
    assert tuple(event.state for event in record.events) == (
        WindowsScmInstallJournalState.PREPARED,
        WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
        WindowsScmInstallJournalState.SCM_OPENED,
        WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
        WindowsScmInstallJournalState.SERVICE_CREATED,
        WindowsScmInstallJournalState.COMPLETED,
    )
    assessment = journal.assess_recovery("tx-success")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED
    )


def test_delayed_auto_start_success_journals_configure_intent(tmp_path):
    item = plan(delayed_auto_start=True)
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    journal = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    )
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=FakeBackend(),
        journal=journal,
    )

    tx.install(
        authorization_id="install-1",
        target=target,
        plan=item,
        now="2026-09-26T09:05:00Z",
        transaction_id="tx-config",
    )

    states = tuple(
        event.state for event in journal.get("tx-config").events
    )
    assert states[-3:] == (
        WindowsScmInstallJournalState.CONFIGURE_INTENT_RECORDED,
        WindowsScmInstallJournalState.DELAYED_AUTO_START_CONFIGURED,
        WindowsScmInstallJournalState.COMPLETED,
    )


def test_config_failure_journals_rollback_before_delete(tmp_path):
    item = plan(delayed_auto_start=True)
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    journal = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    )
    backend = FakeBackend(fail_config=True)
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=backend,
        journal=journal,
    )

    with pytest.raises(WindowsScmInstallationTransactionError):
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
            transaction_id="tx-rollback",
        )

    record = journal.get("tx-rollback")
    assert record.current_state is WindowsScmInstallJournalState.ROLLED_BACK
    assert (
        journal.assess_recovery("tx-rollback").disposition
        is WindowsScmInstallRecoveryDisposition.CLEAN_ROLLED_BACK
    )


def test_rollback_failure_is_durably_held(tmp_path):
    item = plan(delayed_auto_start=True)
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    journal = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    )
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=FakeBackend(fail_config=True, fail_delete=True),
        journal=journal,
    )

    with pytest.raises(WindowsScmInstallationTransactionError):
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
            transaction_id="tx-rollback-failed",
        )

    record = journal.get("tx-rollback-failed")
    assert (
        record.current_state
        is WindowsScmInstallJournalState.ROLLBACK_FAILED
    )
    assessment = journal.assess_recovery("tx-rollback-failed")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition.HOLD_ROLLBACK_FAILED
    )


def test_abrupt_exit_during_create_leaves_create_intent_hold(tmp_path):
    class CrashDuringCreateBackend(FakeBackend):
        def create_service(self, scm_handle, plan, credential_secret):
            self.calls.append(
                ("create_service_crash", scm_handle, plan.service_name)
            )
            raise SystemExit("simulated process death")

    item = plan()
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    journal = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    )
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=CrashDuringCreateBackend(),
        journal=journal,
    )

    with pytest.raises(SystemExit):
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
            transaction_id="tx-create-crash",
        )

    record = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    ).get("tx-create-crash")
    assert (
        record.current_state
        is WindowsScmInstallJournalState.CREATE_INTENT_RECORDED
    )
    assessment = journal.assess_recovery("tx-create-crash")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition
        .HOLD_POSSIBLE_INSTALLED_SERVICE
    )


def test_abrupt_exit_during_configure_leaves_ambiguous_hold(tmp_path):
    class CrashDuringConfigureBackend(FakeBackend):
        def configure_delayed_auto_start(self, service_handle, enabled):
            self.calls.append(
                ("configure_crash", service_handle, enabled)
            )
            raise SystemExit("simulated process death")

    item = plan(delayed_auto_start=True)
    target = target_for(item)
    store = WindowsScmInstallationAuthorizationStore(
        tmp_path / "install.sqlite3"
    )
    issue(store, target)
    journal = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    )
    tx = WindowsScmServiceInstallationTransaction(
        authorization_store=store,
        backend=CrashDuringConfigureBackend(),
        journal=journal,
    )

    with pytest.raises(SystemExit):
        tx.install(
            authorization_id="install-1",
            target=target,
            plan=item,
            now="2026-09-26T09:05:00Z",
            transaction_id="tx-config-crash",
        )

    record = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    ).get("tx-config-crash")
    assert (
        record.current_state
        is WindowsScmInstallJournalState.CONFIGURE_INTENT_RECORDED
    )
    assert (
        journal.assess_recovery("tx-config-crash").disposition
        is WindowsScmInstallRecoveryDisposition
        .HOLD_POSSIBLE_INSTALLED_SERVICE
    )
