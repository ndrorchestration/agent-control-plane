import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_install_authorization import (
    WindowsScmInstallationTarget,
)
from agent_control_plane.windows_scm_install_journal import (
    WindowsScmInstallationJournal,
    WindowsScmInstallJournalState,
    WindowsScmInstallRecoveryDisposition,
)


def target():
    return WindowsScmInstallationTarget(
        service_name="ACPAgentControlPlane",
        manifest_sha256="a" * 64,
        binary_sha256="b" * 64,
        registration_plan_sha256="c" * 64,
    )


def begin(tmp_path, transaction_id="tx-1"):
    journal = WindowsScmInstallationJournal(
        tmp_path / "journal.sqlite3"
    )
    record = journal.begin(
        transaction_id=transaction_id,
        authorization_id="install-auth-1",
        target=target(),
        created_at="2026-09-26T09:00:00Z",
    )
    return journal, record


def append(journal, state, second):
    return journal.append(
        "tx-1",
        state=state,
        occurred_at=f"2026-09-26T09:00:{second:02d}Z",
    )


def test_begin_is_append_only_prepared_record(tmp_path):
    journal, record = begin(tmp_path)
    assert record.current_state is WindowsScmInstallJournalState.PREPARED
    assert len(record.events) == 1
    assert record.events[0].event_index == 0

    same = journal.begin(
        transaction_id="tx-1",
        authorization_id="install-auth-1",
        target=target(),
        created_at="2026-09-26T09:00:00Z",
    )
    assert same == record


def test_transaction_id_conflict_fails_closed(tmp_path):
    journal, _ = begin(tmp_path)
    changed = WindowsScmInstallationTarget(
        service_name="OtherService",
        manifest_sha256="a" * 64,
        binary_sha256="b" * 64,
        registration_plan_sha256="c" * 64,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="transaction_id conflict",
    ):
        journal.begin(
            transaction_id="tx-1",
            authorization_id="install-auth-1",
            target=changed,
            created_at="2026-09-26T09:00:00Z",
        )


def test_clean_success_transition_sequence(tmp_path):
    journal, _ = begin(tmp_path)
    states = (
        WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
        WindowsScmInstallJournalState.SCM_OPENED,
        WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
        WindowsScmInstallJournalState.SERVICE_CREATED,
        WindowsScmInstallJournalState.CONFIGURE_INTENT_RECORDED,
        WindowsScmInstallJournalState.DELAYED_AUTO_START_CONFIGURED,
        WindowsScmInstallJournalState.COMPLETED,
    )
    for second, state in enumerate(states, start=1):
        append(journal, state, second)

    record = journal.get("tx-1")
    assert tuple(event.state for event in record.events) == (
        WindowsScmInstallJournalState.PREPARED,
        *states,
    )
    assessment = journal.assess_recovery("tx-1")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED
    )
    assert assessment.service_mutation_may_exist is True


def test_crash_after_create_intent_is_fail_closed_hold(tmp_path):
    journal, _ = begin(tmp_path)
    append(
        journal,
        WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
        1,
    )
    append(journal, WindowsScmInstallJournalState.SCM_OPENED, 2)
    append(
        journal,
        WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
        3,
    )

    assessment = journal.assess_recovery("tx-1")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition
        .HOLD_POSSIBLE_INSTALLED_SERVICE
    )
    assert assessment.service_mutation_may_exist is True


def test_failure_after_create_intent_remains_ambiguous(tmp_path):
    journal, _ = begin(tmp_path)
    append(
        journal,
        WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
        1,
    )
    append(journal, WindowsScmInstallJournalState.SCM_OPENED, 2)
    append(
        journal,
        WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
        3,
    )
    journal.append(
        "tx-1",
        state=WindowsScmInstallJournalState.FAILED,
        occurred_at="2026-09-26T09:00:04Z",
        error="CreateServiceW returned error",
    )

    assessment = journal.assess_recovery("tx-1")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition
        .HOLD_POSSIBLE_INSTALLED_SERVICE
    )
    assert assessment.service_mutation_may_exist is True


def test_failure_before_create_intent_needs_new_auth_but_no_service_mutation(
    tmp_path,
):
    journal, _ = begin(tmp_path)
    append(
        journal,
        WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
        1,
    )
    journal.append(
        "tx-1",
        state=WindowsScmInstallJournalState.FAILED,
        occurred_at="2026-09-26T09:00:02Z",
        error="SCM open failed",
    )
    assessment = journal.assess_recovery("tx-1")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition
        .NO_SERVICE_MUTATION_NEEDS_NEW_AUTH
    )
    assert assessment.service_mutation_may_exist is False


def test_clean_rollback_classifies_no_remaining_mutation(tmp_path):
    journal, _ = begin(tmp_path)
    for second, state in enumerate(
        (
            WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
            WindowsScmInstallJournalState.SCM_OPENED,
            WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
            WindowsScmInstallJournalState.SERVICE_CREATED,
            WindowsScmInstallJournalState.CONFIGURE_INTENT_RECORDED,
            WindowsScmInstallJournalState.ROLLBACK_DELETE_INTENT_RECORDED,
            WindowsScmInstallJournalState.ROLLED_BACK,
        ),
        start=1,
    ):
        append(journal, state, second)

    assessment = journal.assess_recovery("tx-1")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition.CLEAN_ROLLED_BACK
    )
    assert assessment.service_mutation_may_exist is False


def test_rollback_failure_requires_hold(tmp_path):
    journal, _ = begin(tmp_path)
    for second, state in enumerate(
        (
            WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
            WindowsScmInstallJournalState.SCM_OPENED,
            WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
            WindowsScmInstallJournalState.SERVICE_CREATED,
            WindowsScmInstallJournalState.ROLLBACK_DELETE_INTENT_RECORDED,
            WindowsScmInstallJournalState.ROLLBACK_FAILED,
        ),
        start=1,
    ):
        append(journal, state, second)

    assessment = journal.assess_recovery("tx-1")
    assert (
        assessment.disposition
        is WindowsScmInstallRecoveryDisposition.HOLD_ROLLBACK_FAILED
    )
    assert assessment.service_mutation_may_exist is True


def test_invalid_transition_fails_closed(tmp_path):
    journal, _ = begin(tmp_path)
    with pytest.raises(
        AuthorityValidationError,
        match="invalid installation journal transition",
    ):
        append(
            journal,
            WindowsScmInstallJournalState.SERVICE_CREATED,
            1,
        )


def test_terminal_transaction_rejects_more_events(tmp_path):
    journal, _ = begin(tmp_path)
    journal.append(
        "tx-1",
        state=WindowsScmInstallJournalState.FAILED,
        occurred_at="2026-09-26T09:00:01Z",
        error="pre-mutation failure",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="terminal",
    ):
        journal.append(
            "tx-1",
            state=WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
            occurred_at="2026-09-26T09:00:02Z",
        )
