import os

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_install_journal import (
    WindowsScmInstallJournalState,
    WindowsScmInstallRecoveryAssessment,
    WindowsScmInstallRecoveryDisposition,
)
from agent_control_plane.windows_scm_recovery_inspector import (
    WindowsScmInstallRecoveryInspector,
    WindowsScmLiveServiceConfig,
    WindowsScmRecoveryResolution,
    probe_windows_scm_recovery_query_api,
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
        dependencies_multi_sz="Tcpip\0Dnscache\0\0",
        account_name=r"NT SERVICE\ACPAgentControlPlane",
        credential_reference=None,
        requires_credential_resolution=False,
        delayed_auto_start=False,
        desired_scm_access=3,
        desired_service_access=0x36,
    )


def ambiguous(disposition=None):
    return WindowsScmInstallRecoveryAssessment(
        transaction_id="tx-1",
        current_state=WindowsScmInstallJournalState.CREATE_INTENT_RECORDED,
        disposition=(
            disposition
            or WindowsScmInstallRecoveryDisposition
            .HOLD_POSSIBLE_INSTALLED_SERVICE
        ),
        service_mutation_may_exist=True,
    )


def matching_live():
    item = plan()
    return WindowsScmLiveServiceConfig(
        service_name=item.service_name,
        service_type=item.service_type,
        start_type=item.start_type,
        error_control=item.error_control,
        binary_path_command=item.binary_path_command,
        dependencies=("Tcpip", "Dnscache"),
        account_name=item.account_name,
        display_name=item.display_name,
        delayed_auto_start=False,
    )


class FakeReader:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.calls = []

    def read(self, service_name):
        self.calls.append(service_name)
        if self.error is not None:
            raise self.error
        return self.value


def test_exact_live_match_resolves_ambiguous_hold():
    reader = FakeReader(matching_live())
    inspection = WindowsScmInstallRecoveryInspector(reader).inspect(
        assessment=ambiguous(),
        plan=plan(),
    )
    assert inspection.resolution is WindowsScmRecoveryResolution.INSTALLED_MATCH
    assert inspection.mismatched_fields == ()
    assert reader.calls == ["ACPAgentControlPlane"]


def test_service_absent_resolves_observation_without_mutation():
    inspection = WindowsScmInstallRecoveryInspector(
        FakeReader(None)
    ).inspect(
        assessment=ambiguous(),
        plan=plan(),
    )
    assert inspection.resolution is WindowsScmRecoveryResolution.SERVICE_ABSENT
    assert inspection.live_service is None


def test_live_config_mismatch_remains_hold_and_lists_fields():
    live = matching_live()
    changed = WindowsScmLiveServiceConfig(
        **{
            **live.__dict__,
            "binary_path_command": r'"c:\other\different.exe"',
            "delayed_auto_start": True,
        }
    )
    inspection = WindowsScmInstallRecoveryInspector(
        FakeReader(changed)
    ).inspect(
        assessment=ambiguous(),
        plan=plan(),
    )
    assert (
        inspection.resolution
        is WindowsScmRecoveryResolution.HOLD_LIVE_CONFIG_MISMATCH
    )
    assert inspection.mismatched_fields == (
        "binary_path_command",
        "delayed_auto_start",
    )


def test_query_error_remains_hold_and_records_error():
    inspection = WindowsScmInstallRecoveryInspector(
        FakeReader(error=OSError(5, "access denied"))
    ).inspect(
        assessment=ambiguous(),
        plan=plan(),
    )
    assert (
        inspection.resolution
        is WindowsScmRecoveryResolution.HOLD_LIVE_QUERY_ERROR
    )
    assert "OSError" in inspection.error


def test_clean_journal_disposition_does_not_query_live_scm():
    reader = FakeReader(error=AssertionError("must not query"))
    assessment = WindowsScmInstallRecoveryAssessment(
        transaction_id="tx-clean",
        current_state=WindowsScmInstallJournalState.COMPLETED,
        disposition=WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED,
        service_mutation_may_exist=True,
    )
    inspection = WindowsScmInstallRecoveryInspector(reader).inspect(
        assessment=assessment,
        plan=plan(),
    )
    assert inspection.resolution is WindowsScmRecoveryResolution.NOT_REQUIRED
    assert reader.calls == []


def test_rollback_failed_also_uses_live_inspection():
    inspection = WindowsScmInstallRecoveryInspector(
        FakeReader(None)
    ).inspect(
        assessment=ambiguous(
            WindowsScmInstallRecoveryDisposition.HOLD_ROLLBACK_FAILED
        ),
        plan=plan(),
    )
    assert inspection.resolution is WindowsScmRecoveryResolution.SERVICE_ABSENT


def test_query_probe_is_explicit_off_windows():
    probe = probe_windows_scm_recovery_query_api()
    if os.name == "nt":
        assert probe.is_windows is True
    else:
        assert probe.is_windows is False
        assert probe.available is False
        assert probe.available_exports == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows-only SCM query exports")
def test_windows_query_exports_are_available():
    probe = probe_windows_scm_recovery_query_api()
    assert probe.available is True
    assert probe.available_exports == probe.required_exports


def test_inspector_requires_reader_protocol():
    with pytest.raises(AuthorityValidationError):
        WindowsScmInstallRecoveryInspector(object())
