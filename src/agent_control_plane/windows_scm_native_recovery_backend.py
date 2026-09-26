"""Native Windows SCM backend for authorized recovery deletion."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os

from .authority import AuthorityValidationError


SC_MANAGER_CONNECT = 0x0001
DELETE = 0x00010000

_REQUIRED_RECOVERY_DELETE_EXPORTS = (
    "OpenSCManagerW",
    "OpenServiceW",
    "DeleteService",
    "CloseServiceHandle",
)


@dataclass(frozen=True)
class WindowsScmRecoveryDeleteApiProbe:
    is_windows: bool
    required_exports: tuple[str, ...]
    available_exports: tuple[str, ...]

    @property
    def available(self) -> bool:
        return (
            self.is_windows
            and self.available_exports == self.required_exports
        )


def probe_windows_scm_recovery_delete_api() -> WindowsScmRecoveryDeleteApiProbe:
    if os.name != "nt":
        return WindowsScmRecoveryDeleteApiProbe(
            is_windows=False,
            required_exports=_REQUIRED_RECOVERY_DELETE_EXPORTS,
            available_exports=(),
        )
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    available = tuple(
        name for name in _REQUIRED_RECOVERY_DELETE_EXPORTS
        if hasattr(advapi32, name)
    )
    return WindowsScmRecoveryDeleteApiProbe(
        is_windows=True,
        required_exports=_REQUIRED_RECOVERY_DELETE_EXPORTS,
        available_exports=available,
    )


class WindowsScmNativeRecoveryDeleteApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise AuthorityValidationError(
                "native Windows SCM recovery delete API requires Windows"
            )
        probe = probe_windows_scm_recovery_delete_api()
        if not probe.available:
            missing = tuple(
                name
                for name in probe.required_exports
                if name not in probe.available_exports
            )
            raise AuthorityValidationError(
                f"required Windows SCM recovery delete exports unavailable: {missing}"
            )

        self.advapi32 = ctypes.WinDLL(
            "Advapi32.dll",
            use_last_error=True,
        )

        self.open_scm = self.advapi32.OpenSCManagerW
        self.open_scm.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
        ]
        self.open_scm.restype = wintypes.HANDLE

        self.open_service = self.advapi32.OpenServiceW
        self.open_service.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            wintypes.DWORD,
        ]
        self.open_service.restype = wintypes.HANDLE

        self.delete_service = self.advapi32.DeleteService
        self.delete_service.argtypes = [wintypes.HANDLE]
        self.delete_service.restype = wintypes.BOOL

        self.close_service_handle = self.advapi32.CloseServiceHandle
        self.close_service_handle.argtypes = [wintypes.HANDLE]
        self.close_service_handle.restype = wintypes.BOOL


class WindowsScmNativeRecoveryDeleteBackend:
    """Least-privilege native backend for one exact service deletion."""

    def __init__(self, api=None) -> None:
        self.api = api or WindowsScmNativeRecoveryDeleteApi()

    @staticmethod
    def _raise_last_error(operation: str) -> None:
        raise OSError(
            ctypes.get_last_error(),
            f"{operation} failed",
        )

    def open_scm(self):
        handle = self.api.open_scm(
            None,
            None,
            SC_MANAGER_CONNECT,
        )
        if not handle:
            self._raise_last_error("OpenSCManagerW")
        return handle

    def open_service_for_delete(
        self,
        scm_handle,
        service_name: str,
    ):
        if not scm_handle:
            raise AuthorityValidationError(
                "scm_handle must be non-zero"
            )
        if not isinstance(service_name, str) or not service_name.strip():
            raise AuthorityValidationError(
                "service_name must not be blank"
            )
        handle = self.api.open_service(
            scm_handle,
            service_name.strip(),
            DELETE,
        )
        if not handle:
            self._raise_last_error("OpenServiceW")
        return handle

    def delete_service(self, service_handle) -> None:
        if not service_handle:
            raise AuthorityValidationError(
                "service_handle must be non-zero"
            )
        if not self.api.delete_service(service_handle):
            self._raise_last_error("DeleteService")

    def close_handle(self, handle) -> None:
        if not handle:
            return
        if not self.api.close_service_handle(handle):
            self._raise_last_error("CloseServiceHandle")
