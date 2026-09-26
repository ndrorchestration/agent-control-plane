from pathlib import Path

import pytest

from agent_control_plane.windows_scm_install_authorization import (
    WindowsScmInstallationTarget,
)
from agent_control_plane.windows_scm_install_journal import (
    WindowsScmInstallJournalRecord,
    WindowsScmInstallJournalEvent,
    WindowsScmInstallJournalState,
    WindowsScmInstallRecoveryDisposition,
)
from agent_control_plane.windows_scm_install_recovery import (
    WindowsScmInstallRecoveryDecision,
    WindowsScmInstallRecoveryInspector,
    WindowsScmInstallRecoveryResolver,
    WindowsScmInspectionMatch,
    WindowsScmObservedService,
)
from agent_control_plane.windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
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


def target():
    return WindowsScmInstallationTarget(
        service_name="ACPAgentControlPlane",
        manifest_sha256="a" * 64,
        binary_sha256="b" * 64,
        registration_plan_sha256="c" * 64,
    )


def observed(**changes):
    values = dict(
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path_command=r'"c:\acp\acp-supervisor.exe"',
        service_type=0x10,
        start_type=3,
        error_control=1,
        dependencies_multi_sz=None,
        account_name=r"NT SERVICE\ACPAgentControlPlane",
    )
    values.update(changes)
    return WindowsScmObservedService(**values)


class FakeInspector:
    def __init__(self, item):
        self.item = item
        self.calls = []

    def inspect(self, service_name):
        self.calls.append(service_name)
        return self.item


def record(state):
    event = WindowsScmInstallJournalEvent(
        transaction_id="tx-1",
        event_index=0,
        state=state,
        occurred_at="2026-09-26T10:00:00Z",
        error=None,
    )
    return WindowsScmInstallJournalRecord(
        transaction_id="tx-1",
        authorization_id="auth-1",
        service_name="ACPAgentControlPlane",
        manifest_sha256="a" * 64,
        binary_sha256="b" * 64,
        registration_plan_sha256="c" * 64,
        created_at="2026-09-26T10:00:00Z",
        events=(event,),
    )


def test_absent_service_is_reported_without_hashing():
    inspector = FakeInspector(None)
    hashes = []
    recovery = WindowsScmInstallRecoveryInspector(
        inspector=inspector,
        binary_hasher=lambda path: hashes.append(path) or "b" * 64,
    )

    result = recovery.inspect_exact(
        target=target(),
        plan=plan(),
    )

    assert result.match is WindowsScmInspectionMatch.ABSENT
    assert result.observed is None
    assert hashes == []


def test_exact_service_requires_configuration_and_binary_match():
    inspector = FakeInspector(observed())
    recovery = WindowsScmInstallRecoveryInspector(
        inspector=inspector,
        binary_hasher=lambda path: "b" * 64,
    )

    result = recovery.inspect_exact(
        target=target(),
        plan=plan(),
    )

    assert result.match is WindowsScmInspectionMatch.EXACT_MATCH
    assert result.mismatches == ()
    assert result.binary_sha256 == "b" * 64


def test_configuration_drift_is_identity_conflict():
    inspector = FakeInspector(
        observed(start_type=2, account_name="LocalSystem")
    )
    recovery = WindowsScmInstallRecoveryInspector(
        inspector=inspector,
        binary_hasher=lambda path: "b" * 64,
    )

    result = recovery.inspect_exact(
        target=target(),
        plan=plan(),
    )

    assert result.match is WindowsScmInspectionMatch.MISMATCH
    assert result.mismatches == ("start_type", "account_name")


def test_binary_digest_drift_is_identity_conflict():
    recovery = WindowsScmInstallRecoveryInspector(
        inspector=FakeInspector(observed()),
        binary_hasher=lambda path: "d" * 64,
    )

    result = recovery.inspect_exact(
        target=target(),
        plan=plan(),
    )

    assert result.match is WindowsScmInspectionMatch.MISMATCH
    assert result.mismatches == ("binary_sha256",)


@pytest.mark.parametrize(
    ("journal_disposition", "inspection_match", "expected"),
    [
        (
            WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED,
            WindowsScmInspectionMatch.EXACT_MATCH,
            WindowsScmInstallRecoveryDecision.CLEAN_INSTALLED,
        ),
        (
            WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED,
            WindowsScmInspectionMatch.ABSENT,
            WindowsScmInstallRecoveryDecision.HOLD_EXPECTED_SERVICE_MISSING,
        ),
        (
            WindowsScmInstallRecoveryDisposition.CLEAN_ROLLED_BACK,
            WindowsScmInspectionMatch.ABSENT,
            WindowsScmInstallRecoveryDecision.CLEAN_ROLLED_BACK,
        ),
        (
            WindowsScmInstallRecoveryDisposition.HOLD_POSSIBLE_INSTALLED_SERVICE,
            WindowsScmInspectionMatch.EXACT_MATCH,
            WindowsScmInstallRecoveryDecision.HOLD_EXACT_SERVICE_PRESENT,
        ),
        (
            WindowsScmInstallRecoveryDisposition.HOLD_POSSIBLE_INSTALLED_SERVICE,
            WindowsScmInspectionMatch.ABSENT,
            WindowsScmInstallRecoveryDecision.NEW_INSTALL_AUTH_REQUIRED,
        ),
        (
            WindowsScmInstallRecoveryDisposition.NO_SERVICE_MUTATION_NEEDS_NEW_AUTH,
            WindowsScmInspectionMatch.ABSENT,
            WindowsScmInstallRecoveryDecision.NEW_INSTALL_AUTH_REQUIRED,
        ),
    ],
)
def test_recovery_resolution_is_fail_closed(
    journal_disposition,
    inspection_match,
    expected,
):
    inspection = type("Inspection", (), {})()
    from agent_control_plane.windows_scm_install_recovery import (
        WindowsScmInspectionResult,
    )
    inspection = WindowsScmInspectionResult(
        match=inspection_match,
        observed=(observed() if inspection_match is not WindowsScmInspectionMatch.ABSENT else None),
        binary_sha256=("b" * 64 if inspection_match is WindowsScmInspectionMatch.EXACT_MATCH else None),
        mismatches=(),
    )

    resolution = WindowsScmInstallRecoveryResolver().resolve(
        journal_record=record(WindowsScmInstallJournalState.FAILED),
        journal_disposition=journal_disposition,
        inspection=inspection,
    )

    assert resolution.decision is expected
    assert resolution.cleanup_mutation_authorized is False


def test_any_mismatch_forces_identity_conflict():
    from agent_control_plane.windows_scm_install_recovery import (
        WindowsScmInspectionResult,
    )
    inspection = WindowsScmInspectionResult(
        match=WindowsScmInspectionMatch.MISMATCH,
        observed=observed(display_name="Other"),
        binary_sha256="b" * 64,
        mismatches=("display_name",),
    )

    resolution = WindowsScmInstallRecoveryResolver().resolve(
        journal_record=record(WindowsScmInstallJournalState.FAILED),
        journal_disposition=(
            WindowsScmInstallRecoveryDisposition.HOLD_POSSIBLE_INSTALLED_SERVICE
        ),
        inspection=inspection,
    )

    assert (
        resolution.decision
        is WindowsScmInstallRecoveryDecision.HOLD_IDENTITY_CONFLICT
    )
    assert resolution.cleanup_mutation_authorized is False
