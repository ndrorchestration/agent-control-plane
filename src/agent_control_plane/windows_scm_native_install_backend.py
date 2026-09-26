"""Native Windows SCM mutation backend for authorized installation transactions.

This module provides the concrete Windows implementation of the existing
WindowsScmInstallationBackend protocol. It does not itself issue or validate
installation authorization; callers must use WindowsScmServiceInstallationTransaction.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)


SERVICE_CONFIG_DELAYED_AUTO_START_INFO = 3

_REQUIRED_INSTALL_EXPORTS = (
    "OpenSCManagerW",
    "CreateServiceW",
    "ChangeServiceConfig2W",
    "DeleteService",
    "CloseServiceHandle",
)


class ServiceDelayedAutoStartInfo(ctypes.Structure):
    _fields_ = [("fDelayedAutostart", wintypes.BOOL)]


@dataclass(frozen=True)
class WindowsScmNativeInstallApiProbe:
    is_windows: bool
    required_exports: tuple[str, ...]
    available_exports: tuple[str, ...]

    @property
    def available(self) -> bool:
        return (
            self.is_windows
            and self.available_exports == self.required_exports
        )


def probe_windows_scm_install_api() -> WindowsScmNativeInstallApiProbe:
    if os.name != "nt":
        return WindowsScmNativeInstallApiProbe(
            is_windows=False,
            required_exports=_REQUIRED_INSTALL_EXPORTS,
            available_exports=(),
        )
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    available = tuple(
        name for name in _REQUIRED_INSTALL_EXPORTS
        if hasattr(advapi32, name)
    )
    return WindowsScmNativeInstallApiProbe(
        is_windows=True,
        required_exports=_REQUIRED_INSTALL_EXPORTS,
        available_exports=available,
    )


class WindowsScmNativeInstallApi:
    """Thin ctypes wrapper over the native SCM mutation calls."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise AuthorityValidationError(
                "native Windows SCM install API requires Windows"
            )
        probe = probe_windows_scm_install_api()
        if not probe.available:
            missing = tuple(
                name
                for name in probe.required_exports
                if name not in probe.available_exports
            )
            raise AuthorityValidationError(
                f"required Windows SCM install exports unavailable: {missing}"
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

        self.create_service = self.advapi32.CreateServiceW
        self.create_service.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
        ]
        self.create_service.restype = wintypes.HANDLE

        self.change_service_config2 = (
            self.advapi32.ChangeServiceConfig2W
        )
        self.change_service_config2.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        self.change_service_config2.restype = wintypes.BOOL

        self.delete_service = self.advapi32.DeleteService
        self.delete_service.argtypes = [wintypes.HANDLE]
        self.delete_service.restype = wintypes.BOOL

        self.close_service_handle = self.advapi32.CloseServiceHandle
        self.close_service_handle.argtypes = [wintypes.HANDLE]
        self.close_service_handle.restype = wintypes.BOOL


class WindowsScmNativeInstallationBackend:
    """Concrete backend for WindowsScmServiceInstallationTransaction."""

    def __init__(self, api=None) -> None:
        self.api = api or WindowsScmNativeInstallApi()

    @staticmethod
    def _raise_last_error(operation: str) -> None:
        error = ctypes.get_last_error()
        raise OSError(error, f"{operation} failed")

    def open_scm(self, desired_access: int):
        if (
            isinstance(desired_access, bool)
            or not isinstance(desired_access, int)
            or desired_access <= 0
        ):
            raise AuthorityValidationError(
                "desired_access must be an integer > 0"
            )
        handle = self.api.open_scm(
            None,
            None,
            desired_access,
        )
        if not handle:
            self._raise_last_error("OpenSCManagerW")
        return handle

    def create_service(
        self,
        scm_handle,
        plan: WindowsScmServiceRegistrationPlan,
        credential_secret: Optional[str],
    ):
        if not scm_handle:
            raise AuthorityValidationError(
                "scm_handle must be non-zero"
            )
        if not isinstance(plan, WindowsScmServiceRegistrationPlan):
            raise AuthorityValidationError(
                "plan must be WindowsScmServiceRegistrationPlan"
            )
        if plan.requires_credential_resolution:
            if not isinstance(credential_secret, str) or not credential_secret:
                raise AuthorityValidationError(
                    "credential secret required by registration plan"
                )
        elif credential_secret is not None:
            raise AuthorityValidationError(
                "credential secret supplied for passwordless registration plan"
            )

        dependencies_buffer = None
        dependencies_pointer = None
        if plan.dependencies_multi_sz is not None:
            dependencies_buffer = ctypes.create_unicode_buffer(
                plan.dependencies_multi_sz
            )
            dependencies_pointer = ctypes.cast(
                dependencies_buffer,
                wintypes.LPCWSTR,
            )

        service_handle = self.api.create_service(
            scm_handle,
            plan.service_name,
            plan.display_name,
            plan.desired_service_access,
            plan.service_type,
            plan.start_type,
            plan.error_control,
            plan.binary_path_command,
            None,
            None,
            dependencies_pointer,
            plan.account_name,
            credential_secret,
        )
        # Keep the MULTI_SZ buffer alive through the native call.
        _ = dependencies_buffer
        if not service_handle:
            self._raise_last_error("CreateServiceW")
        return service_handle

    def configure_delayed_auto_start(
        self,
        service_handle,
        enabled: bool,
    ) -> None:
        if not service_handle:
            raise AuthorityValidationError(
                "service_handle must be non-zero"
            )
        if not isinstance(enabled, bool):
            raise AuthorityValidationError(
                "enabled must be bool"
            )
        info = ServiceDelayedAutoStartInfo(
            fDelayedAutostart=wintypes.BOOL(enabled),
        )
        ok = self.api.change_service_config2(
            service_handle,
            SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
            ctypes.cast(
                ctypes.byref(info),
                wintypes.LPVOID,
            ),
        )
        if not ok:
            self._raise_last_error("ChangeServiceConfig2W")

    def delete_service(self, service_handle) -> None:
        if not service_handle:
            raise AuthorityValidationError(
                "service_handle must be non-zero"
            )
        ok = self.api.delete_service(service_handle)
        if not ok:
            self._raise_last_error("DeleteService")

    def close_handle(self, handle) -> None:
        if not handle:
            return
        ok = self.api.close_service_handle(handle)
        if not ok:
            self._raise_last_error("CloseServiceHandle")
