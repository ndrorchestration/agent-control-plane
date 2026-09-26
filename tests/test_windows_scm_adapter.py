import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.supervisor_service_host import SupervisorServiceHostEvent
from agent_control_plane.windows_scm_adapter import (
    WindowsScmControlAdapter,
    WindowsScmControlCode,
    WindowsScmControlDisposition,
)


def test_windows_scm_stop_maps_to_host_stop():
    result = WindowsScmControlAdapter().translate(
        WindowsScmControlCode.STOP
    )
    assert result.disposition is WindowsScmControlDisposition.HOST_EVENT
    assert result.host_event is SupervisorServiceHostEvent.STOP


def test_windows_scm_shutdown_maps_to_host_shutdown():
    result = WindowsScmControlAdapter().translate(
        WindowsScmControlCode.SHUTDOWN
    )
    assert result.host_event is SupervisorServiceHostEvent.SHUTDOWN


def test_windows_scm_preshutdown_remains_distinct():
    result = WindowsScmControlAdapter().translate(
        WindowsScmControlCode.PRESHUTDOWN
    )
    assert result.host_event is SupervisorServiceHostEvent.PRESHUTDOWN


def test_windows_scm_interrogate_is_status_only():
    result = WindowsScmControlAdapter().translate(
        WindowsScmControlCode.INTERROGATE
    )
    assert result.disposition is WindowsScmControlDisposition.STATUS_ONLY
    assert result.host_event is None


@pytest.mark.parametrize(
    "code",
    [
        WindowsScmControlCode.PAUSE,
        WindowsScmControlCode.CONTINUE,
        0xDEADBEEF,
    ],
)
def test_unsupported_windows_scm_controls_fail_closed(code):
    with pytest.raises(AuthorityValidationError):
        WindowsScmControlAdapter().translate(code)
