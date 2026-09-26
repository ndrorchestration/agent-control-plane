"""Read-only live Windows SCM inspection for install-recovery holds."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
import os
from typing import Optional, Protocol, runtime_checkable

from .authority import AuthorityValidationError
from .windows_scm_install_journal import (
    WindowsScmInstallRecoveryAssessment,
    WindowsScmInstallRecoveryDisposition,
)
from .windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)


SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_CONFIG = 0x0001
SERVICE_CONFIG_DELAYED_AUTO_START_INFO = 3
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_SERVICE_DOES_NOT_EXIST = 1060

_REQUIRED_QUERY_EXPORTS = (
    "OpenSCManagerW",
    "OpenServiceW",
    "QueryServiceConfigW",
    "QueryServiceConfig2W",
    "CloseServiceHandle",
)


class NativeQueryServiceConfig(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwStartType", wintypes.DWORD),
        ("dwErrorControl", wintypes.DWORD),
        ("lpBinaryPathName", ctypes.c_void_p),
        ("lpLoadOrderGroup", ctypes.c_void_p),
        ("dwTagId", wintypes.DWORD),
        ("lpDependencies", ctypes.c_void_p),
        ("lpServiceStartName", ctypes.c_void_p),
        ("lpDisplayName", ctypes.c_void_p),
    ]


class NativeDelayedAutoStartInfo(ctypes.Structure):
    _fields_ = [("fDelayedAutostart", wintypes.BOOL)]


@dataclass(frozen=True)
class WindowsScmLiveServiceConfig:
    service_name: str
    service_type: int
    start_type: int
    error_control: int
    binary_path_command: str
    dependencies: tuple[str, ...]
    account_name: str
    display_name: str
    delayed_auto_start: bool


@dataclass(frozen=True)
class WindowsScmRecoveryQueryApiProbe:
    is_windows: bool
    required_exports: tuple[str, ...]
    available_exports: tuple[str, ...]

    @property
    def available(self) -> bool:
        return (
            self.is_windows
            and self.required_exports == self.available_exports
        )


def probe_windows_scm_recovery_query_api() -> WindowsScmRecoveryQueryApiProbe:
    if os.name != "nt":
        return WindowsScmRecoveryQueryApiProbe(
            is_windows=False,
            required_exports=_REQUIRED_QUERY_EXPORTS,
            available_exports=(),
        )
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    available = tuple(
        name for name in _REQUIRED_QUERY_EXPORTS if hasattr(advapi32, name)
    )
    return WindowsScmRecoveryQueryApiProbe(
        is_windows=True,
        required_exports=_REQUIRED_QUERY_EXPORTS,
        available_exports=available,
    )


def _wstring(pointer: int | None) -> str:
    if not pointer:
        return ""
    return ctypes.wstring_at(pointer)


def _multi_sz(pointer: int | None) -> tuple[str, ...]:
    if not pointer:
        return ()
    wchar_size = ctypes.sizeof(ctypes.c_wchar)
    result: list[str] = []
    address = int(pointer)
    while True:
        value = ctypes.wstring_at(address)
        if not value:
            break
        result.append(value)
        address += (len(value) + 1) * wchar_size
    return tuple(result)


def _plan_dependencies(
    plan: WindowsScmServiceRegistrationPlan,
) -> tuple[str, ...]:
    if plan.dependencies_multi_sz is None:
        return ()
    return tuple(
        item
        for item in plan.dependencies_multi_sz.split("\0")
        if item
    )


@runtime_checkable
class WindowsScmLiveConfigReader(Protocol):
    def read(
        self,
        service_name: str,
    ) -> Optional[WindowsScmLiveServiceConfig]: ...


class WindowsScmNativeLiveConfigReader:
    """Read one service's configuration without mutating SCM state."""

    def __init__(self, api=None) -> None:
        if api is not None:
            self.api = api
            return
        if os.name != "nt":
            raise AuthorityValidationError(
                "native Windows SCM recovery query requires Windows"
            )
        probe = probe_windows_scm_recovery_query_api()
        if not probe.available:
            missing = tuple(
                name for name in probe.required_exports
                if name not in probe.available_exports
            )
            raise AuthorityValidationError(
                f"required Windows SCM query exports unavailable: {missing}"
            )
        advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)

        open_scm = advapi32.OpenSCManagerW
        open_scm.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
        ]
        open_scm.restype = wintypes.HANDLE

        open_service = advapi32.OpenServiceW
        open_service.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            wintypes.DWORD,
        ]
        open_service.restype = wintypes.HANDLE

        query_config = advapi32.QueryServiceConfigW
        query_config.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query_config.restype = wintypes.BOOL

        query_config2 = advapi32.QueryServiceConfig2W
        query_config2.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query_config2.restype = wintypes.BOOL

        close_handle = advapi32.CloseServiceHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        self.api = type(
            "_WindowsScmQueryApi",
            (),
            {
                "open_scm": staticmethod(open_scm),
                "open_service": staticmethod(open_service),
                "query_config": staticmethod(query_config),
                "query_config2": staticmethod(query_config2),
                "close_handle": staticmethod(close_handle),
            },
        )()

    @staticmethod
    def _error(operation: str) -> OSError:
        code = ctypes.get_last_error()
        return OSError(code, f"{operation} failed")

    def read(
        self,
        service_name: str,
    ) -> Optional[WindowsScmLiveServiceConfig]:
        if not isinstance(service_name, str) or not service_name.strip():
            raise AuthorityValidationError(
                "service_name must not be blank"
            )
        name = service_name.strip()
        scm_handle = None
        service_handle = None
        try:
            scm_handle = self.api.open_scm(
                None,
                None,
                SC_MANAGER_CONNECT,
            )
            if not scm_handle:
                raise self._error("OpenSCManagerW")

            service_handle = self.api.open_service(
                scm_handle,
                name,
                SERVICE_QUERY_CONFIG,
            )
            if not service_handle:
                error = ctypes.get_last_error()
                if error == ERROR_SERVICE_DOES_NOT_EXIST:
                    return None
                raise OSError(error, "OpenServiceW failed")

            needed = wintypes.DWORD(0)
            ok = self.api.query_config(
                service_handle,
                None,
                0,
                ctypes.byref(needed),
            )
            if ok:
                raise AuthorityValidationError(
                    "QueryServiceConfigW unexpectedly succeeded without buffer"
                )
            error = ctypes.get_last_error()
            if error != ERROR_INSUFFICIENT_BUFFER or needed.value == 0:
                raise OSError(error, "QueryServiceConfigW size query failed")

            buffer = ctypes.create_string_buffer(needed.value)
            ok = self.api.query_config(
                service_handle,
                ctypes.cast(buffer, ctypes.c_void_p),
                needed.value,
                ctypes.byref(needed),
            )
            if not ok:
                raise self._error("QueryServiceConfigW")

            config = ctypes.cast(
                buffer,
                ctypes.POINTER(NativeQueryServiceConfig),
            ).contents

            delayed = NativeDelayedAutoStartInfo()
            delayed_needed = wintypes.DWORD(0)
            ok = self.api.query_config2(
                service_handle,
                SERVICE_CONFIG_DELAYED_AUTO_START_INFO,
                ctypes.cast(ctypes.byref(delayed), ctypes.c_void_p),
                ctypes.sizeof(delayed),
                ctypes.byref(delayed_needed),
            )
            if not ok:
                raise self._error("QueryServiceConfig2W")

            return WindowsScmLiveServiceConfig(
                service_name=name,
                service_type=int(config.dwServiceType),
                start_type=int(config.dwStartType),
                error_control=int(config.dwErrorControl),
                binary_path_command=_wstring(config.lpBinaryPathName),
                dependencies=_multi_sz(config.lpDependencies),
                account_name=_wstring(config.lpServiceStartName),
                display_name=_wstring(config.lpDisplayName),
                delayed_auto_start=bool(delayed.fDelayedAutostart),
            )
        finally:
            if service_handle:
                self.api.close_handle(service_handle)
            if scm_handle:
                self.api.close_handle(scm_handle)


class WindowsScmRecoveryResolution(str, Enum):
    NOT_REQUIRED = "not_required"
    SERVICE_ABSENT = "service_absent"
    INSTALLED_MATCH = "installed_match"
    HOLD_LIVE_CONFIG_MISMATCH = "hold_live_config_mismatch"
    HOLD_LIVE_QUERY_ERROR = "hold_live_query_error"


@dataclass(frozen=True)
class WindowsScmInstallRecoveryInspection:
    journal_disposition: WindowsScmInstallRecoveryDisposition
    resolution: WindowsScmRecoveryResolution
    live_service: Optional[WindowsScmLiveServiceConfig]
    mismatched_fields: tuple[str, ...] = ()
    error: Optional[str] = None


class WindowsScmInstallRecoveryInspector:
    """Narrow ambiguous journal holds using read-only live SCM evidence."""

    def __init__(self, reader: WindowsScmLiveConfigReader) -> None:
        if not isinstance(reader, WindowsScmLiveConfigReader):
            raise AuthorityValidationError(
                "reader must implement WindowsScmLiveConfigReader"
            )
        self.reader = reader

    def inspect(
        self,
        *,
        assessment: WindowsScmInstallRecoveryAssessment,
        plan: WindowsScmServiceRegistrationPlan,
    ) -> WindowsScmInstallRecoveryInspection:
        if not isinstance(
            assessment,
            WindowsScmInstallRecoveryAssessment,
        ):
            raise AuthorityValidationError(
                "assessment must be WindowsScmInstallRecoveryAssessment"
            )
        if not isinstance(plan, WindowsScmServiceRegistrationPlan):
            raise AuthorityValidationError(
                "plan must be WindowsScmServiceRegistrationPlan"
            )

        ambiguous = assessment.disposition in (
            WindowsScmInstallRecoveryDisposition
            .HOLD_POSSIBLE_INSTALLED_SERVICE,
            WindowsScmInstallRecoveryDisposition.HOLD_ROLLBACK_FAILED,
        )
        if not ambiguous:
            return WindowsScmInstallRecoveryInspection(
                journal_disposition=assessment.disposition,
                resolution=WindowsScmRecoveryResolution.NOT_REQUIRED,
                live_service=None,
            )

        try:
            live = self.reader.read(plan.service_name)
        except Exception as exc:
            return WindowsScmInstallRecoveryInspection(
                journal_disposition=assessment.disposition,
                resolution=WindowsScmRecoveryResolution.HOLD_LIVE_QUERY_ERROR,
                live_service=None,
                error=f"{type(exc).__name__}: {exc}",
            )

        if live is None:
            return WindowsScmInstallRecoveryInspection(
                journal_disposition=assessment.disposition,
                resolution=WindowsScmRecoveryResolution.SERVICE_ABSENT,
                live_service=None,
            )

        expected = {
            "service_type": plan.service_type,
            "start_type": plan.start_type,
            "error_control": plan.error_control,
            "binary_path_command": plan.binary_path_command,
            "dependencies": _plan_dependencies(plan),
            "account_name": plan.account_name,
            "display_name": plan.display_name,
            "delayed_auto_start": plan.delayed_auto_start,
        }
        mismatches = tuple(
            field_name
            for field_name, expected_value in expected.items()
            if getattr(live, field_name) != expected_value
        )
        if mismatches:
            return WindowsScmInstallRecoveryInspection(
                journal_disposition=assessment.disposition,
                resolution=(
                    WindowsScmRecoveryResolution.HOLD_LIVE_CONFIG_MISMATCH
                ),
                live_service=live,
                mismatched_fields=mismatches,
            )
        return WindowsScmInstallRecoveryInspection(
            journal_disposition=assessment.disposition,
            resolution=WindowsScmRecoveryResolution.INSTALLED_MATCH,
            live_service=live,
        )
