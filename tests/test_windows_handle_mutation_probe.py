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


class _RENAME_UNION(ctypes.Union):
    _fields_ = [
        ("ReplaceIfExists", wintypes.BOOLEAN),
        ("Flags", wintypes.DWORD),
    ]


class _FILE_RENAME_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("u", _RENAME_UNION),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.DWORD),
        ("FileName", wintypes.WCHAR * 1),
    ]


_FILE_RENAME_INFO_CLASS = 3
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_ADD_FILE = 0x00000002
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000


def open_directory_handle(path: Path):
    api = kernel32()
    handle = api.CreateFileW(
        str(path),
        _FILE_LIST_DIRECTORY | _FILE_ADD_FILE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if ctypes.cast(handle, ctypes.c_void_p).value == _INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateFileW(directory) failed")
    return api, handle


def rename_by_source_handle_relative_to_parent(
    source_handle,
    parent_handle,
    target_name: str,
):
    api = kernel32()
    name_bytes = target_name.encode("utf-16-le")
    file_name_offset = _FILE_RENAME_INFO.FileName.offset
    size = file_name_offset + len(name_bytes) + ctypes.sizeof(wintypes.WCHAR)
    buffer = ctypes.create_string_buffer(size)
    info = ctypes.cast(buffer, ctypes.POINTER(_FILE_RENAME_INFO)).contents
    info.ReplaceIfExists = True
    info.RootDirectory = parent_handle
    info.FileNameLength = len(name_bytes)
    ctypes.memmove(
        ctypes.addressof(buffer) + file_name_offset,
        name_bytes,
        len(name_bytes),
    )
    ok = api.SetFileInformationByHandle(
        source_handle,
        _FILE_RENAME_INFO_CLASS,
        ctypes.byref(buffer),
        size,
    )
    if not ok:
        raise OSError(
            ctypes.get_last_error(),
            "SetFileInformationByHandle(FileRenameInfo) failed",
        )


@pytest.mark.xfail(
    reason=(
        "SetFileInformationByHandle(FileRenameInfo) rejects non-NULL "
        "RootDirectory with ERROR_INVALID_PARAMETER on this Windows host; "
        "handle-relative rename requires a different API path"
    ),
    strict=True,
)
def test_handle_relative_atomic_replace_uses_held_parent_directory(tmp_path):
    target = tmp_path / "target.txt"
    temp = tmp_path / "prepared.tmp"
    target.write_bytes(b"old")
    temp.write_bytes(b"new")

    api, parent_handle = open_directory_handle(tmp_path.resolve())
    _, source_handle = open_handle(
        temp.resolve(),
        access=_DELETE | _FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )
    try:
        rename_by_source_handle_relative_to_parent(
            source_handle,
            parent_handle,
            "target.txt",
        )
    finally:
        api.CloseHandle(source_handle)
        api.CloseHandle(parent_handle)

    assert target.read_bytes() == b"new"
    assert not temp.exists()


def test_handle_rename_with_absolute_destination_path(tmp_path):
    target = tmp_path / "target-absolute.txt"
    temp = tmp_path / "prepared-absolute.tmp"
    target.write_bytes(b"old")
    temp.write_bytes(b"new")

    api, source_handle = open_handle(
        temp.resolve(),
        access=_DELETE | _FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )
    try:
        rename_by_source_handle_relative_to_parent(
            source_handle,
            None,
            str(target.resolve()),
        )
    finally:
        api.CloseHandle(source_handle)

    assert not temp.exists()
    assert target.read_bytes() == b"new"


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [
        ("Status", ctypes.c_ssize_t),
        ("Information", ctypes.c_size_t),
    ]


_FILE_RENAME_INFORMATION_NT_CLASS = 10


def rename_by_nt_source_handle_relative_to_parent(
    source_handle,
    parent_handle,
    target_name: str,
):
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtSetInformationFile.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_IO_STATUS_BLOCK),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.INT,
    ]
    ntdll.NtSetInformationFile.restype = ctypes.c_long

    name_bytes = target_name.encode("utf-16-le")
    file_name_offset = _FILE_RENAME_INFO.FileName.offset
    size = file_name_offset + len(name_bytes) + ctypes.sizeof(wintypes.WCHAR)
    buffer = ctypes.create_string_buffer(size)
    info = ctypes.cast(buffer, ctypes.POINTER(_FILE_RENAME_INFO)).contents
    info.ReplaceIfExists = True
    info.RootDirectory = parent_handle
    info.FileNameLength = len(name_bytes)
    ctypes.memmove(
        ctypes.addressof(buffer) + file_name_offset,
        name_bytes,
        len(name_bytes),
    )
    iosb = _IO_STATUS_BLOCK()
    status = ntdll.NtSetInformationFile(
        source_handle,
        ctypes.byref(iosb),
        buffer,
        size,
        _FILE_RENAME_INFORMATION_NT_CLASS,
    )
    if status < 0:
        raise OSError(
            status & 0xFFFFFFFF,
            "NtSetInformationFile(FileRenameInformation) failed",
        )
    return status, iosb.Status


def test_nt_handle_relative_atomic_replace_uses_held_parent_directory(tmp_path):
    target = tmp_path / "target-nt.txt"
    temp = tmp_path / "prepared-nt.tmp"
    target.write_bytes(b"old")
    temp.write_bytes(b"new")

    api, parent_handle = open_directory_handle(tmp_path.resolve())
    _, source_handle = open_handle(
        temp.resolve(),
        access=_DELETE | _FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )
    try:
        status, iosb_status = rename_by_nt_source_handle_relative_to_parent(
            source_handle,
            parent_handle,
            "target-nt.txt",
        )
    finally:
        api.CloseHandle(source_handle)
        api.CloseHandle(parent_handle)

    assert status == 0
    assert iosb_status == 0
    assert target.read_bytes() == b"new"
    assert not temp.exists()


def test_nt_handle_relative_rename_stays_bound_to_held_parent_after_path_swap(tmp_path):
    trusted = tmp_path / "trusted"
    attacker = tmp_path / "attacker"
    trusted.mkdir()
    attacker.mkdir()
    target = trusted / "target.txt"
    temp = trusted / "prepared.tmp"
    target.write_bytes(b"old")
    temp.write_bytes(b"new")

    api, parent_handle = open_directory_handle(trusted.resolve())
    _, source_handle = open_handle(
        temp.resolve(),
        access=_DELETE | _FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
    )
    displaced = tmp_path / "trusted-displaced"
    try:
        with pytest.raises(PermissionError):
            trusted.rename(displaced)
        status, iosb_status = rename_by_nt_source_handle_relative_to_parent(
            source_handle,
            parent_handle,
            "target.txt",
        )
    finally:
        api.CloseHandle(source_handle)
        api.CloseHandle(parent_handle)

    assert status == 0
    assert iosb_status == 0
    assert target.read_bytes() == b"new"
    assert not temp.exists()
    assert attacker.exists()
