"""Windows-only handle identity probe for executor TOCTOU hardening.

This module opens an existing filesystem object with CreateFileW, optionally
using FILE_FLAG_OPEN_REPARSE_POINT, and derives the stable identity exposed by
GetFileInformationByHandle. It performs no mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class WindowsHandleIdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowsHandleIdentity:
    path: str
    volume_serial_number: int
    file_index: int
    file_attributes: int
    number_of_links: int


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def _kernel32():
    if os.name != "nt":
        raise WindowsHandleIdentityError(
            "Windows handle identity is only available on Windows"
        )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def capture_windows_handle_identity(
    path: str | Path,
    *,
    open_reparse_point: bool = True,
) -> WindowsHandleIdentity:
    """Open one exact existing object and return its handle-derived identity."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise WindowsHandleIdentityError("path must be absolute")

    kernel32 = _kernel32()
    flags = _FILE_FLAG_BACKUP_SEMANTICS
    if open_reparse_point:
        flags |= _FILE_FLAG_OPEN_REPARSE_POINT

    handle = kernel32.CreateFileW(
        str(candidate),
        0,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    handle_value = ctypes.cast(handle, ctypes.c_void_p).value
    if handle_value == _INVALID_HANDLE_VALUE:
        code = ctypes.get_last_error()
        raise WindowsHandleIdentityError(
            f"CreateFileW failed for {candidate}: winerror={code}"
        )

    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            code = ctypes.get_last_error()
            raise WindowsHandleIdentityError(
                f"GetFileInformationByHandle failed: winerror={code}"
            )
        file_index = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
        return WindowsHandleIdentity(
            path=str(candidate),
            volume_serial_number=int(info.dwVolumeSerialNumber),
            file_index=file_index,
            file_attributes=int(info.dwFileAttributes),
            number_of_links=int(info.nNumberOfLinks),
        )
    finally:
        kernel32.CloseHandle(handle)
