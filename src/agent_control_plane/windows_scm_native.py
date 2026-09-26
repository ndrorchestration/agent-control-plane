"""Dependency-free native Windows SCM ABI bindings for ACP.

This module binds only the native functions and status structure needed by a
future Windows service host. It does not install or start a service.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from typing import Callable

from .authority import AuthorityValidationError
from .windows_scm_service_host import WindowsScmServiceStatus


SERVICE_WIN32_OWN_PROCESS = 0x00000010
ERROR_SERVICE_SPECIFIC_ERROR = 1066
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063

_REQUIRED_EXPORTS = (
    "StartServiceCtrlDispatcherW",
    "RegisterServiceCtrlHandlerExW",
    "SetServiceStatus",
)


class NativeServiceStatus(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
    ]


class NativeServiceTableEntry(ctypes.Structure):
    _fields_ = [
        ("lpServiceName", wintypes.LPWSTR),
        ("lpServiceProc", ctypes.c_void_p),
    ]


@dataclass(frozen=True)
class WindowsScmNativeApiProbe:
    is_windows: bool
    required_exports: tuple[str, ...]
    available_exports: tuple[str, ...]

    @property
    def available(self) -> bool:
        return (
            self.is_windows
            and self.available_exports == self.required_exports
        )


def native_service_status(
    status: WindowsScmServiceStatus,
) -> NativeServiceStatus:
    if not isinstance(status, WindowsScmServiceStatus):
        raise AuthorityValidationError(
            "status must be WindowsScmServiceStatus"
        )
    return NativeServiceStatus(
        dwServiceType=SERVICE_WIN32_OWN_PROCESS,
        dwCurrentState=int(status.state),
        dwControlsAccepted=int(status.accepted_controls),
        dwWin32ExitCode=status.win32_exit_code,
        dwServiceSpecificExitCode=status.service_specific_exit_code,
        dwCheckPoint=status.checkpoint,
        dwWaitHint=status.wait_hint_ms,
    )


def probe_windows_scm_native_api() -> WindowsScmNativeApiProbe:
    if os.name != "nt":
        return WindowsScmNativeApiProbe(
            is_windows=False,
            required_exports=_REQUIRED_EXPORTS,
            available_exports=(),
        )

    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    available = tuple(
        name for name in _REQUIRED_EXPORTS if hasattr(advapi32, name)
    )
    return WindowsScmNativeApiProbe(
        is_windows=True,
        required_exports=_REQUIRED_EXPORTS,
        available_exports=available,
    )


class WindowsScmNativeBindings:
    """Validated ctypes bindings to the minimal SCM service-host API."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise AuthorityValidationError(
                "native Windows SCM bindings require Windows"
            )

        probe = probe_windows_scm_native_api()
        if not probe.available:
            missing = tuple(
                name
                for name in probe.required_exports
                if name not in probe.available_exports
            )
            raise AuthorityValidationError(
                f"required Windows SCM exports unavailable: {missing}"
            )

        self.advapi32 = ctypes.WinDLL(
            "Advapi32.dll",
            use_last_error=True,
        )

        self.start_service_ctrl_dispatcher = (
            self.advapi32.StartServiceCtrlDispatcherW
        )
        self.start_service_ctrl_dispatcher.argtypes = [
            ctypes.c_void_p,
        ]
        self.start_service_ctrl_dispatcher.restype = wintypes.BOOL

        self.register_service_ctrl_handler_ex = (
            self.advapi32.RegisterServiceCtrlHandlerExW
        )
        self.register_service_ctrl_handler_ex.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            wintypes.LPVOID,
        ]
        self.register_service_ctrl_handler_ex.restype = wintypes.HANDLE

        self.set_service_status = self.advapi32.SetServiceStatus
        self.set_service_status.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(NativeServiceStatus),
        ]
        self.set_service_status.restype = wintypes.BOOL

    @staticmethod
    def service_main_callback_type():
        return ctypes.WINFUNCTYPE(
            None,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPWSTR),
        )

    @staticmethod
    def handler_ex_callback_type():
        return ctypes.WINFUNCTYPE(
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
        )

    def publish_status(
        self,
        status_handle,
        status: WindowsScmServiceStatus,
    ) -> None:
        if not status_handle:
            raise AuthorityValidationError(
                "status_handle must be non-zero"
            )
        native = native_service_status(status)
        ok = self.set_service_status(
            status_handle,
            ctypes.byref(native),
        )
        if not ok:
            error = ctypes.get_last_error()
            raise OSError(
                error,
                "SetServiceStatus failed",
            )


    def make_service_main_callback(self, callback: Callable):
        if not callable(callback):
            raise AuthorityValidationError(
                "service main callback must be callable"
            )
        return self.service_main_callback_type()(callback)

    def make_handler_ex_callback(self, callback: Callable):
        if not callable(callback):
            raise AuthorityValidationError(
                "handler callback must be callable"
            )
        return self.handler_ex_callback_type()(callback)

    def register_handler(
        self,
        service_name: str,
        handler_callback,
    ):
        if not isinstance(service_name, str) or not service_name.strip():
            raise AuthorityValidationError(
                "service_name must not be blank"
            )
        if handler_callback is None:
            raise AuthorityValidationError(
                "handler_callback must not be None"
            )
        handle = self.register_service_ctrl_handler_ex(
            service_name.strip(),
            ctypes.cast(handler_callback, ctypes.c_void_p),
            None,
        )
        if not handle:
            error = ctypes.get_last_error()
            raise OSError(
                error,
                "RegisterServiceCtrlHandlerExW failed",
            )
        return handle

    def dispatch(
        self,
        service_name: str,
        service_main_callback,
    ) -> None:
        if not isinstance(service_name, str) or not service_name.strip():
            raise AuthorityValidationError(
                "service_name must not be blank"
            )
        if service_main_callback is None:
            raise AuthorityValidationError(
                "service_main_callback must not be None"
            )
        table_type = NativeServiceTableEntry * 2
        table = table_type(
            NativeServiceTableEntry(
                lpServiceName=service_name.strip(),
                lpServiceProc=ctypes.cast(
                    service_main_callback,
                    ctypes.c_void_p,
                ),
            ),
            NativeServiceTableEntry(
                lpServiceName=None,
                lpServiceProc=None,
            ),
        )
        ok = self.start_service_ctrl_dispatcher(
            ctypes.cast(table, ctypes.c_void_p),
        )
        if not ok:
            error = ctypes.get_last_error()
            raise OSError(
                error,
                "StartServiceCtrlDispatcherW failed",
            )
