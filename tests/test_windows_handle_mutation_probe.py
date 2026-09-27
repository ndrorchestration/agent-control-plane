from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only handle probe")

_DELETE = 0x00010000
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_DISPOSITION_INFO_CLASS = 4
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _FILE_DISPOSITION_INFO(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOLEAN)]


def kernel32():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    api.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    api.SetFileInformationByHandle.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


def open_handle(
    path: Path,
    *,
    access: int,
    share: int,
):
    api = kernel32()
    handle = api.CreateFileW(
        str(path),
        access,
        share,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if ctypes.cast(handle, ctypes.c_void_p).value == _INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    return api, handle


def test_excluding_delete_share_blocks_path_replacement(tmp_path):
    target = tmp_path / "target.txt"
    replacement = tmp_path / "replacement.txt"
    target.write_bytes(b"original")
    replacement.write_bytes(b"replacement")

    api, handle = open_handle(
        target,
        access=_FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
    )
    try:
        with pytest.raises(PermissionError):
            os.replace(replacement, target)
        assert target.read_bytes() == b"original"
        assert replacement.read_bytes() == b"replacement"
    finally:
        api.CloseHandle(handle)


def test_handle_based_disposition_deletes_exact_opened_temp_file(tmp_path):
    target = tmp_path / "delete-me.txt"
    target.write_bytes(b"temporary")

    api, handle = open_handle(
        target,
        access=_DELETE | _FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )
    try:
        disposition = _FILE_DISPOSITION_INFO(DeleteFile=True)
        ok = api.SetFileInformationByHandle(
            handle,
            _FILE_DISPOSITION_INFO_CLASS,
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
        )
        if not ok:
            raise OSError(
                ctypes.get_last_error(),
                "SetFileInformationByHandle(FileDispositionInfo) failed",
            )
    finally:
        api.CloseHandle(handle)

    assert not target.exists()
