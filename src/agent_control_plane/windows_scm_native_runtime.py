"""Native Windows SCM callback runtime over ACP's accepted host contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .authority import AuthorityValidationError
from .supervisor_service import SupervisorStopReason
from .windows_scm_adapter import WindowsScmControlCode
from .windows_scm_native import (
    ERROR_SERVICE_SPECIFIC_ERROR,
    WindowsScmNativeBindings,
)
from .windows_scm_service_host import WindowsScmServiceHostContract


ERROR_SUCCESS = 0
ERROR_CALL_NOT_IMPLEMENTED = 120


@dataclass(frozen=True)
class WindowsScmNativeRuntimeResult:
    stop_reason: Optional[SupervisorStopReason]
    service_error: Optional[str]


class WindowsScmNativeCallbackRuntime:
    """Bridge native SCM callbacks into ACP's existing service-host contract."""

    def __init__(
        self,
        *,
        service_name: str,
        service_callable: Callable[[], None],
        host: Optional[WindowsScmServiceHostContract] = None,
        bindings=None,
    ) -> None:
        if not isinstance(service_name, str) or not service_name.strip():
            raise AuthorityValidationError(
                "service_name must not be blank"
            )
        if not callable(service_callable):
            raise AuthorityValidationError(
                "service_callable must be callable"
            )
        if host is not None and not isinstance(
            host,
            WindowsScmServiceHostContract,
        ):
            raise AuthorityValidationError(
                "host must be WindowsScmServiceHostContract or None"
            )
        self.service_name = service_name.strip()
        self.service_callable = service_callable
        self.host = host or WindowsScmServiceHostContract()
        self.bindings = bindings or WindowsScmNativeBindings()
        self.status_handle = None
        self.service_error: Optional[str] = None
        self._handler_callback = None
        self._service_main_callback = None

    def _publish(self) -> None:
        if self.status_handle is None:
            raise AuthorityValidationError(
                "native SCM status handle is not registered"
            )
        self.bindings.publish_status(
            self.status_handle,
            self.host.status(),
        )

    def handler_ex(
        self,
        control_code: int,
        event_type=0,
        event_data=None,
        context=None,
    ) -> int:
        try:
            self.host.handler_ex(control_code)
            self._publish()
            return ERROR_SUCCESS
        except AuthorityValidationError:
            return ERROR_CALL_NOT_IMPLEMENTED

    def run_service_main(self) -> WindowsScmNativeRuntimeResult:
        self.host.service_main_enter()
        self._handler_callback = self.bindings.make_handler_ex_callback(
            self.handler_ex
        )
        self.status_handle = self.bindings.register_handler(
            self.service_name,
            self._handler_callback,
        )
        self._publish()

        self.host.mark_running()
        self._publish()

        try:
            self.service_callable()
        except Exception as exc:
            self.service_error = f"{type(exc).__name__}: {exc}"
            stopped = self.host.mark_stopped(
                win32_exit_code=ERROR_SERVICE_SPECIFIC_ERROR,
                service_specific_exit_code=1,
            )
            self.bindings.publish_status(
                self.status_handle,
                stopped,
            )
            return WindowsScmNativeRuntimeResult(
                stop_reason=self.host.stop_reason(),
                service_error=self.service_error,
            )

        stopped = self.host.mark_stopped()
        self.bindings.publish_status(
            self.status_handle,
            stopped,
        )
        return WindowsScmNativeRuntimeResult(
            stop_reason=self.host.stop_reason(),
            service_error=None,
        )

    def service_main(self, argc=0, argv=None) -> None:
        # Exceptions are contained within run_service_main so no Python
        # exception crosses the native callback boundary.
        self.run_service_main()

    def dispatch(self) -> WindowsScmNativeRuntimeResult:
        self._service_main_callback = (
            self.bindings.make_service_main_callback(
                self.service_main
            )
        )
        self.bindings.dispatch(
            self.service_name,
            self._service_main_callback,
        )
        return WindowsScmNativeRuntimeResult(
            stop_reason=self.host.stop_reason(),
            service_error=self.service_error,
        )
