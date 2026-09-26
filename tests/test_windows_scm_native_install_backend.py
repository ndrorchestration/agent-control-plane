import ctypes
import os

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_native_install_backend import (
    SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
    ServiceDelayedAutoStartInfo,
    WindowsScmNativeInstallApi,
    WindowsScmNativeInstallationBackend,
    probe_windows_scm_install_api,
)
from agent_control_plane.windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)


def plan(
    *,
    dependencies_multi_sz=None,
    requires_credential_resolution=False,
):
    return WindowsScmServiceRegistrationPlan(
        manifest_sha256="a" * 64,
        service_name="ACPAgentControlPlane",
        display_name="ACP Agent Control Plane",
        binary_path_command=r'"c:\acp\acp-supervisor.exe"',
        service_type=0x10,
        start_type=3,
        error_control=1,
        dependencies_multi_sz=dependencies_multi_sz,
        account_name=(
            r".\acp-service-user"
            if requires_credential_resolution
            else r"NT SERVICE\ACPAgentControlPlane"
        ),
        credential_reference=(
            "vault:acp-service"
            if requires_credential_resolution
            else None
        ),
        requires_credential_resolution=requires_credential_resolution,
        delayed_auto_start=False,
        desired_scm_access=3,
        desired_service_access=0x36,
    )


class FakeApi:
    def __init__(
        self,
        *,
        open_handle=101,
        service_handle=202,
        config_ok=True,
        delete_ok=True,
        close_ok=True,
    ):
        self.open_handle = open_handle
        self.service_handle = service_handle
        self.config_ok = config_ok
        self.delete_ok = delete_ok
        self.close_ok = close_ok
        self.calls = []

    def open_scm(self, machine, database, desired_access):
        self.calls.append(
            ("open_scm", machine, database, desired_access)
        )
        return self.open_handle

    def create_service(self, *args):
        self.calls.append(("create_service", args))
        return self.service_handle

    def change_service_config2(self, service_handle, info_level, info):
        delayed = ctypes.cast(
            info,
            ctypes.POINTER(ServiceDelayedAutoStartInfo),
        ).contents
        self.calls.append(
            (
                "change_service_config2",
                service_handle,
                info_level,
                bool(delayed.fDelayedAutostart),
            )
        )
        return self.config_ok

    def delete_service(self, service_handle):
        self.calls.append(("delete_service", service_handle))
        return self.delete_ok

    def close_service_handle(self, handle):
        self.calls.append(("close_service_handle", handle))
        return self.close_ok


def test_open_scm_uses_exact_desired_access():
    api = FakeApi()
    backend = WindowsScmNativeInstallationBackend(api=api)

    handle = backend.open_scm(3)

    assert handle == 101
    assert api.calls == [("open_scm", None, None, 3)]


def test_create_service_maps_registration_plan_exactly():
    api = FakeApi()
    backend = WindowsScmNativeInstallationBackend(api=api)
    item = plan(dependencies_multi_sz="Tcpip\0Dnscache\0\0")

    handle = backend.create_service(
        101,
        item,
        None,
    )

    assert handle == 202
    call = api.calls[0]
    assert call[0] == "create_service"
    args = call[1]
    assert args[0] == 101
    assert args[1] == item.service_name
    assert args[2] == item.display_name
    assert args[3] == item.desired_service_access
    assert args[4] == item.service_type
    assert args[5] == item.start_type
    assert args[6] == item.error_control
    assert args[7] == item.binary_path_command
    assert args[8] is None
    assert args[9] is None
    assert args[10] is not None
    assert args[11] == item.account_name
    assert args[12] is None


def test_create_service_requires_secret_only_when_plan_requires_it():
    api = FakeApi()
    backend = WindowsScmNativeInstallationBackend(api=api)
    protected = plan(requires_credential_resolution=True)

    with pytest.raises(
        AuthorityValidationError,
        match="credential secret required",
    ):
        backend.create_service(101, protected, None)

    handle = backend.create_service(
        101,
        protected,
        "opaque-resolved-secret",
    )
    assert handle == 202
    args = api.calls[-1][1]
    assert args[12] == "opaque-resolved-secret"


def test_passwordless_plan_rejects_unexpected_secret():
    backend = WindowsScmNativeInstallationBackend(api=FakeApi())
    with pytest.raises(
        AuthorityValidationError,
        match="passwordless",
    ):
        backend.create_service(
            101,
            plan(),
            "should-not-be-present",
        )


def test_delayed_auto_start_uses_config2_info_level():
    api = FakeApi()
    backend = WindowsScmNativeInstallationBackend(api=api)

    backend.configure_delayed_auto_start(202, True)

    assert api.calls == [
        (
            "change_service_config2",
            202,
            SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
            True,
        )
    ]


def test_delete_and_close_use_native_api():
    api = FakeApi()
    backend = WindowsScmNativeInstallationBackend(api=api)

    backend.delete_service(202)
    backend.close_handle(202)
    backend.close_handle(101)

    assert api.calls == [
        ("delete_service", 202),
        ("close_service_handle", 202),
        ("close_service_handle", 101),
    ]


def test_close_none_is_noop():
    api = FakeApi()
    backend = WindowsScmNativeInstallationBackend(api=api)
    backend.close_handle(None)
    assert api.calls == []


def test_probe_is_explicit_off_windows():
    probe = probe_windows_scm_install_api()
    if os.name == "nt":
        assert probe.is_windows is True
    else:
        assert probe.is_windows is False
        assert probe.available is False
        assert probe.available_exports == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native SCM install API")
def test_windows_install_api_exports_and_signatures_load():
    probe = probe_windows_scm_install_api()
    assert probe.available is True
    assert probe.available_exports == probe.required_exports

    api = WindowsScmNativeInstallApi()
    assert api.open_scm.restype is not None
    assert api.create_service.restype is not None
    assert api.change_service_config2.restype is not None
    assert api.delete_service.restype is not None
    assert api.close_service_handle.restype is not None


@pytest.mark.skipif(os.name == "nt", reason="Non-Windows fail-closed behavior")
def test_native_install_api_fails_closed_off_windows():
    with pytest.raises(
        AuthorityValidationError,
        match="requires Windows",
    ):
        WindowsScmNativeInstallApi()
