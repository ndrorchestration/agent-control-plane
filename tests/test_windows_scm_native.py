import ctypes
import os

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.windows_scm_native import (
    ERROR_SERVICE_SPECIFIC_ERROR,
    SERVICE_WIN32_OWN_PROCESS,
    WindowsScmNativeBindings,
    native_service_status,
    probe_windows_scm_native_api,
)
from agent_control_plane.windows_scm_service_host import (
    WindowsScmAcceptedControl,
    WindowsScmServiceStatus,
    WindowsScmServiceState,
)


def test_native_status_maps_all_fields():
    status = WindowsScmServiceStatus(
        state=WindowsScmServiceState.STOP_PENDING,
        accepted_controls=WindowsScmAcceptedControl.NONE,
        win32_exit_code=ERROR_SERVICE_SPECIFIC_ERROR,
        service_specific_exit_code=17,
        checkpoint=4,
        wait_hint_ms=2500,
    )
    native = native_service_status(status)

    assert native.dwServiceType == SERVICE_WIN32_OWN_PROCESS
    assert native.dwCurrentState == int(WindowsScmServiceState.STOP_PENDING)
    assert native.dwControlsAccepted == 0
    assert native.dwWin32ExitCode == ERROR_SERVICE_SPECIFIC_ERROR
    assert native.dwServiceSpecificExitCode == 17
    assert native.dwCheckPoint == 4
    assert native.dwWaitHint == 2500


def test_probe_is_explicit_on_non_windows():
    probe = probe_windows_scm_native_api()
    if os.name == "nt":
        assert probe.is_windows is True
    else:
        assert probe.is_windows is False
        assert probe.available is False
        assert probe.available_exports == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native SCM bindings")
def test_windows_native_probe_has_required_exports():
    probe = probe_windows_scm_native_api()
    assert probe.available is True
    assert probe.available_exports == probe.required_exports


@pytest.mark.skipif(os.name != "nt", reason="Windows-only native SCM bindings")
def test_windows_native_bindings_load_callback_abi():
    bindings = WindowsScmNativeBindings()

    service_main_type = bindings.service_main_callback_type()
    handler_type = bindings.handler_ex_callback_type()

    service_main = service_main_type(lambda argc, argv: None)
    handler = handler_type(
        lambda control, event_type, event_data, context: 0
    )

    assert service_main is not None
    assert handler is not None
    assert bindings.start_service_ctrl_dispatcher.restype is not None
    assert bindings.register_service_ctrl_handler_ex.restype is not None
    assert bindings.set_service_status.restype is not None


@pytest.mark.skipif(os.name == "nt", reason="Non-Windows fail-closed behavior")
def test_native_bindings_fail_closed_off_windows():
    with pytest.raises(
        AuthorityValidationError,
        match="require Windows",
    ):
        WindowsScmNativeBindings()


def test_native_status_requires_typed_status():
    with pytest.raises(AuthorityValidationError):
        native_service_status(object())
