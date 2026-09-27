"""Windows-only handle-relative mutation primitive.

Experimental engineering adapter for disposable ACP executor fixtures.
It is not an authorization boundary and must not be used to infer
High-Assurance or real-repository execution authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class WindowsHandleMutationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowsHandleMutationResult:
    ntstatus: int
    destination_name: str


_DELETE = 0x00010000
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_ADD_FILE = 0x00000002
_FILE_RENAME_INFORMATION_CLASS = 10
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [
        ("Status", ctypes.c_ssize_t),
        ("Information", ctypes.c_size_t),
    ]


class _FILE_RENAME_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ReplaceIfExists", wintypes.BOOLEAN),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.ULONG),
        ("FileName", wintypes.WCHAR * 1),
    ]


def _validate(prepared: Path, parent: Path, name: str) -> None:
    if os.name != "nt":
        raise WindowsHandleMutationError("Windows-only mutation adapter")
    if not prepared.is_absolute() or not parent.is_absolute():
        raise WindowsHandleMutationError("paths must be absolute")
    if not name or name in {".", ".."} or "\\" in name or "/" in name:
        raise WindowsHandleMutationError("destination_name must be a leaf name")
    if not prepared.is_file():
        raise WindowsHandleMutationError("prepared_file must be an existing file")
    if not parent.is_dir():
        raise WindowsHandleMutationError("destination_parent must be a directory")


def _open(path: Path, access: int, flags: int):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    handle = api.CreateFileW(
        str(path), access, _FILE_SHARE_ALL, None, _OPEN_EXISTING, flags, None
    )
    if ctypes.cast(handle, ctypes.c_void_p).value == _INVALID_HANDLE_VALUE:
        raise WindowsHandleMutationError(
            f"CreateFileW failed: winerror={ctypes.get_last_error()}"
        )
    return api, handle


def replace_file_relative_to_held_parent(
    *, prepared_file: str | Path, destination_parent: str | Path,
    destination_name: str,
) -> WindowsHandleMutationResult:
    prepared = Path(prepared_file)
    parent = Path(destination_parent)
    _validate(prepared, parent, destination_name)

    api, parent_handle = _open(
        parent, _FILE_LIST_DIRECTORY | _FILE_ADD_FILE,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
    )
    _, source_handle = _open(
        prepared, _DELETE | _FILE_READ_ATTRIBUTES, _FILE_FLAG_OPEN_REPARSE_POINT
    )
    try:
        name_bytes = destination_name.encode("utf-16-le")
        offset = _FILE_RENAME_INFORMATION.FileName.offset
        size = offset + len(name_bytes) + ctypes.sizeof(wintypes.WCHAR)
        buffer = ctypes.create_string_buffer(size)
        info = ctypes.cast(
            buffer, ctypes.POINTER(_FILE_RENAME_INFORMATION)
        ).contents
        info.ReplaceIfExists = True
        info.RootDirectory = parent_handle
        info.FileNameLength = len(name_bytes)
        ctypes.memmove(ctypes.addressof(buffer) + offset, name_bytes, len(name_bytes))

        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtSetInformationFile.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_IO_STATUS_BLOCK), wintypes.LPVOID,
            wintypes.ULONG, wintypes.INT,
        ]
        ntdll.NtSetInformationFile.restype = ctypes.c_long
        iosb = _IO_STATUS_BLOCK()
        status = ntdll.NtSetInformationFile(
            source_handle, ctypes.byref(iosb), buffer, size,
            _FILE_RENAME_INFORMATION_CLASS,
        )
        if status < 0:
            raise WindowsHandleMutationError(
                f"NtSetInformationFile failed: ntstatus=0x{status & 0xFFFFFFFF:08x}"
            )
        return WindowsHandleMutationResult(
            ntstatus=int(status), destination_name=destination_name
        )
    finally:
        api.CloseHandle(source_handle)
        api.CloseHandle(parent_handle)
