import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.supervisor_service import SupervisorStopReason
from agent_control_plane.windows_scm_adapter import WindowsScmControlCode
from agent_control_plane.windows_scm_native import (
    ERROR_SERVICE_SPECIFIC_ERROR,
)
from agent_control_plane.windows_scm_native_runtime import (
    ERROR_CALL_NOT_IMPLEMENTED,
    ERROR_SUCCESS,
    WindowsScmNativeCallbackRuntime,
)
from agent_control_plane.windows_scm_service_host import (
    WindowsScmServiceState,
)


class FakeBindings:
    def __init__(self):
        self.statuses = []
        self.registered_service_name = None
        self.dispatched_service_name = None
        self.handler_callback = None
        self.service_main_callback = None

    def make_handler_ex_callback(self, callback):
        return callback

    def make_service_main_callback(self, callback):
        return callback

    def register_handler(self, service_name, handler_callback):
        self.registered_service_name = service_name
        self.handler_callback = handler_callback
        return 123

    def publish_status(self, status_handle, status):
        assert status_handle == 123
        self.statuses.append(status)

    def dispatch(self, service_name, service_main_callback):
        self.dispatched_service_name = service_name
        self.service_main_callback = service_main_callback
        service_main_callback(0, None)


def test_dispatch_runs_service_main_and_stop_control_to_stopped():
    bindings = FakeBindings()
    holder = {}

    def service_callable():
        runtime = holder["runtime"]
        result = runtime.handler_ex(
            int(WindowsScmControlCode.STOP),
            0,
            None,
            None,
        )
        assert result == ERROR_SUCCESS
        assert runtime.host.stop_reason() is SupervisorStopReason.SERVICE_STOP

    runtime = WindowsScmNativeCallbackRuntime(
        service_name="ACP-Test",
        service_callable=service_callable,
        bindings=bindings,
    )
    holder["runtime"] = runtime

    result = runtime.dispatch()

    assert bindings.registered_service_name == "ACP-Test"
    assert bindings.dispatched_service_name == "ACP-Test"
    assert tuple(status.state for status in bindings.statuses) == (
        WindowsScmServiceState.START_PENDING,
        WindowsScmServiceState.RUNNING,
        WindowsScmServiceState.STOP_PENDING,
        WindowsScmServiceState.STOPPED,
    )
    assert result.stop_reason is SupervisorStopReason.SERVICE_STOP
    assert result.service_error is None


def test_interrogate_republishes_current_status_without_stop():
    bindings = FakeBindings()
    holder = {}

    def service_callable():
        runtime = holder["runtime"]
        before = len(bindings.statuses)
        result = runtime.handler_ex(
            int(WindowsScmControlCode.INTERROGATE),
            0,
            None,
            None,
        )
        assert result == ERROR_SUCCESS
        assert len(bindings.statuses) == before + 1
        assert runtime.host.stop_reason() is None

    runtime = WindowsScmNativeCallbackRuntime(
        service_name="ACP-Test",
        service_callable=service_callable,
        bindings=bindings,
    )
    holder["runtime"] = runtime
    result = runtime.dispatch()

    assert result.stop_reason is None
    assert bindings.statuses[-1].state is WindowsScmServiceState.STOPPED


def test_pause_control_fails_closed_without_state_change():
    bindings = FakeBindings()
    holder = {}

    def service_callable():
        runtime = holder["runtime"]
        before = runtime.host.status()
        result = runtime.handler_ex(
            int(WindowsScmControlCode.PAUSE),
            0,
            None,
            None,
        )
        assert result == ERROR_CALL_NOT_IMPLEMENTED
        assert runtime.host.status() == before

    runtime = WindowsScmNativeCallbackRuntime(
        service_name="ACP-Test",
        service_callable=service_callable,
        bindings=bindings,
    )
    holder["runtime"] = runtime
    runtime.dispatch()


def test_service_exception_is_contained_and_published_as_service_error():
    bindings = FakeBindings()

    def service_callable():
        raise RuntimeError("boom")

    runtime = WindowsScmNativeCallbackRuntime(
        service_name="ACP-Test",
        service_callable=service_callable,
        bindings=bindings,
    )
    result = runtime.dispatch()

    assert "RuntimeError: boom" == result.service_error
    assert bindings.statuses[-1].state is WindowsScmServiceState.STOPPED
    assert (
        bindings.statuses[-1].win32_exit_code
        == ERROR_SERVICE_SPECIFIC_ERROR
    )
    assert bindings.statuses[-1].service_specific_exit_code == 1


def test_service_main_registration_failure_does_not_escape_callback():
    class FailingBindings(FakeBindings):
        def register_handler(self, service_name, handler_callback):
            raise RuntimeError("register failed")

    bindings = FailingBindings()
    runtime = WindowsScmNativeCallbackRuntime(
        service_name="ACP-Test",
        service_callable=lambda: None,
        bindings=bindings,
    )

    # Fake dispatcher invokes the callback synchronously. The callback must
    # contain the registration exception rather than propagate across the ABI.
    result = runtime.dispatch()

    assert result.stop_reason is None
    assert result.service_error == "RuntimeError: register failed"
    assert bindings.statuses == []


def test_blank_service_name_fails_closed():
    with pytest.raises(AuthorityValidationError):
        WindowsScmNativeCallbackRuntime(
            service_name=" ",
            service_callable=lambda: None,
            bindings=FakeBindings(),
        )
