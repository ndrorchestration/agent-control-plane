"""Read-only native Windows SCM service inspection for install recovery."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_install_recovery import (
    WindowsScmObservedService,
)


SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_CONFIG = 0x0001
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_SERVICE_DOES_NOT_EXIST = 1060

_REQUIRED_INSPECTION_EXPORTS = (
    "OpenSCManagerW",
    "OpenServiceW",
    "QueryServiceConfigW",
    "CloseServiceHandle",
)


class QueryServiceConfigWStruct(ctypes.Structure):
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


@dataclass(frozen=True)
class WindowsScmReadOnlyApiProbe:
    is_windows: bool
    required_exports: tuple[str, ...]
    available_exports: tuple[str, ...]

    @property
    def available(self) -> bool:
        return (
            self.is_windows
            and self.available_exports == self.required_exports
        )


def probe_windows_scm_readonly_api() -> WindowsScmReadOnlyApiProbe:
    if os.name != "nt":
        return WindowsScmReadOnlyApiProbe(
            is_windows=False,
            required_exports=_REQUIRED_INSPECTION_EXPORTS,
            available_exports=(),
        )
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    available = tuple(
        name
        for name in _REQUIRED_INSPECTION_EXPORTS
        if hasattr(advapi32, name)
    )
    return WindowsScmReadOnlyApiProbe(
        is_windows=True,
        required_exports=_REQUIRED_INSPECTION_EXPORTS,
        available_exports=available,
    )


def _wstring(pointer) -> str:
    if not pointer:
        return ""
    return ctypes.wstring_at(pointer)


def _multi_sz(pointer) -> Optional[str]:
    if not pointer:
        return None
    values: list[str] = []
    offset = 0
    wchar_size = ctypes.sizeof(ctypes.c_wchar)
    while True:
        current = ctypes.wstring_at(pointer + offset * wchar_size)
        if current == "":
            break
        values.append(current)
        offset += len(current) + 1
    if not values:
        return None
    return "\0".join(values) + "\0\0"


class WindowsScmReadOnlyNativeApi:
    """Native read-only SCM bindings used only for recovery inspection."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise AuthorityValidationError(
                "native Windows SCM inspection requires Windows"
            )
        probe = probe_windows_scm_readonly_api()
        if not probe.available:
            missing = tuple(
                name
                for name in probe.required_exports
                if name not in probe.available_exports
            )
            raise AuthorityValidationError(
                f"required Windows SCM inspection exports unavailable: {missing}"
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

        self.query_service_config = self.advapi32.QueryServiceConfigW
        self.query_service_config.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.query_service_config.restype = wintypes.BOOL

        self.close_service_handle = self.advapi32.CloseServiceHandle
        self.close_service_handle.argtypes = [wintypes.HANDLE]
        self.close_service_handle.restype = wintypes.BOOL

    def read_config(
        self,
        service_handle,
        service_name: str,
    ) -> WindowsScmObservedService:
        needed = wintypes.DWORD(0)
        ctypes.set_last_error(0)
        self.query_service_config(
            service_handle,
            None,
            0,
            ctypes.byref(needed),
        )
        error = ctypes.get_last_error()
        if error != ERROR_INSUFFICIENT_BUFFER or needed.value == 0:
            raise OSError(
                error,
                "QueryServiceConfigW size probe failed",
            )

        buffer = ctypes.create_string_buffer(needed.value)
        ctypes.set_last_error(0)
        ok = self.query_service_config(
            service_handle,
            ctypes.cast(buffer, ctypes.c_void_p),
            needed.value,
            ctypes.byref(needed),
        )
        if not ok:
            error = ctypes.get_last_error()
            raise OSError(error, "QueryServiceConfigW failed")

        config = ctypes.cast(
            buffer,
            ctypes.POINTER(QueryServiceConfigWStruct),
        ).contents
        return WindowsScmObservedService(
            service_name=service_name,
            display_name=_wstring(config.lpDisplayName),
            binary_path_command=_wstring(config.lpBinaryPathName),
            service_type=int(config.dwServiceType),
            start_type=int(config.dwStartType),
            error_control=int(config.dwErrorControl),
            dependencies_multi_sz=_multi_sz(config.lpDependencies),
            account_name=_wstring(config.lpServiceStartName),
        )


class WindowsScmNativeReadOnlyInspector:
    """Open and inspect one service without mutating SCM state."""

    def __init__(self, api=None) -> None:
        self.api = api or WindowsScmReadOnlyNativeApi()

    def inspect(
        self,
        service_name: str,
    ) -> Optional[WindowsScmObservedService]:
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
                error = ctypes.get_last_error()
                raise OSError(error, "OpenSCManagerW failed")

            ctypes.set_last_error(0)
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

            return self.api.read_config(service_handle, name)
        finally:
            if service_handle:
                self.api.close_service_handle(service_handle)
            if scm_handle:
                self.api.close_service_handle(scm_handle)
