import os

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_install_recovery import (
    WindowsScmObservedService,
)
from agent_control_plane.windows_scm_readonly_inspector import (
    ERROR_SERVICE_DOES_NOT_EXIST,
    SC_MANAGER_CONNECT,
    SERVICE_QUERY_CONFIG,
    WindowsScmNativeReadOnlyInspector,
    WindowsScmReadOnlyNativeApi,
    probe_windows_scm_readonly_api,
)


def observed():
    return WindowsScmObservedService(
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path_command=r'"c:\acp\acp-supervisor.exe"',
        service_type=0x10,
        start_type=3,
        error_control=1,
        dependencies_multi_sz=None,
        account_name=r"NT SERVICE\ACPAgentControlPlane",
    )


class FakeApi:
    def __init__(
        self,
        *,
        scm_handle=101,
        service_handle=202,
        error=0,
        config=None,
    ):
        self.scm_handle = scm_handle
        self.service_handle = service_handle
        self.error = error
        self.config = config or observed()
        self.calls = []

    def open_scm(self, machine, database, access):
        self.calls.append(("open_scm", machine, database, access))
        return self.scm_handle

    def open_service(self, scm_handle, service_name, access):
        self.calls.append(
            ("open_service", scm_handle, service_name, access)
        )
        return self.service_handle

    def read_config(self, service_handle, service_name):
        self.calls.append(
            ("read_config", service_handle, service_name)
        )
        return self.config

    def close_service_handle(self, handle):
        self.calls.append(("close", handle))
        return True

    def last_error(self):
        return self.error


def test_present_service_is_read_only_and_handles_close():
    api = FakeApi()
    inspector = WindowsScmNativeReadOnlyInspector(api=api)

    result = inspector.inspect("ACPAgentControlPlane")

    assert result == observed()
    assert api.calls == [
        ("open_scm", None, None, SC_MANAGER_CONNECT),
        (
            "open_service",
            101,
            "ACPAgentControlPlane",
            SERVICE_QUERY_CONFIG,
        ),
        ("read_config", 202, "ACPAgentControlPlane"),
        ("close", 202),
        ("close", 101),
    ]


def test_missing_service_returns_none_and_closes_scm():
    api = FakeApi(
        service_handle=0,
        error=ERROR_SERVICE_DOES_NOT_EXIST,
    )
    inspector = WindowsScmNativeReadOnlyInspector(api=api)

    result = inspector.inspect("ACPAgentControlPlane")

    assert result is None
    assert api.calls[-1] == ("close", 101)
    assert not any(call[0] == "read_config" for call in api.calls)


def test_non_missing_open_service_error_is_surfaced():
    api = FakeApi(service_handle=0, error=5)
    inspector = WindowsScmNativeReadOnlyInspector(api=api)

    with pytest.raises(OSError) as exc:
        inspector.inspect("ACPAgentControlPlane")

    assert exc.value.errno == 5
    assert api.calls[-1] == ("close", 101)


def test_open_scm_error_is_surfaced_without_close():
    api = FakeApi(scm_handle=0, error=5)
    inspector = WindowsScmNativeReadOnlyInspector(api=api)

    with pytest.raises(OSError) as exc:
        inspector.inspect("ACPAgentControlPlane")

    assert exc.value.errno == 5
    assert api.calls == [
        ("open_scm", None, None, SC_MANAGER_CONNECT),
    ]


def test_blank_service_name_fails_closed():
    inspector = WindowsScmNativeReadOnlyInspector(api=FakeApi())
    with pytest.raises(AuthorityValidationError):
        inspector.inspect(" ")


def test_probe_is_explicit_off_windows():
    probe = probe_windows_scm_readonly_api()
    if os.name == "nt":
        assert probe.is_windows is True
    else:
        assert probe.is_windows is False
        assert probe.available is False
        assert probe.available_exports == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native SCM inspection")
def test_windows_readonly_api_exports_and_signatures_load():
    probe = probe_windows_scm_readonly_api()
    assert probe.available is True
    assert probe.available_exports == probe.required_exports

    api = WindowsScmReadOnlyNativeApi()
    assert api.open_scm.restype is not None
    assert api.open_service.restype is not None
    assert api.query_service_config.restype is not None
    assert api.close_service_handle.restype is not None


@pytest.mark.skipif(os.name == "nt", reason="Non-Windows fail-closed behavior")
def test_native_readonly_api_fails_closed_off_windows():
    with pytest.raises(
        AuthorityValidationError,
        match="requires Windows",
    ):
        WindowsScmReadOnlyNativeApi()
