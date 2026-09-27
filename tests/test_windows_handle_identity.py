from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_control_plane.windows_handle_identity import (
    WindowsHandleIdentityError,
    capture_windows_handle_identity,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only handle probe")


def test_file_handle_identity_is_stable_across_reopen(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"first")

    first = capture_windows_handle_identity(target.resolve())
    second = capture_windows_handle_identity(target.resolve())

    assert first.volume_serial_number == second.volume_serial_number
    assert first.file_index == second.file_index
    assert first.number_of_links >= 1


def test_directory_handle_identity_is_stable(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    first = capture_windows_handle_identity(root.resolve())
    second = capture_windows_handle_identity(root.resolve())

    assert first.volume_serial_number == second.volume_serial_number
    assert first.file_index == second.file_index


def test_replacement_changes_file_identity(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"first")
    first = capture_windows_handle_identity(target.resolve())

    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"second")
    os.replace(replacement, target)

    second = capture_windows_handle_identity(target.resolve())

    assert (
        first.volume_serial_number,
        first.file_index,
    ) != (
        second.volume_serial_number,
        second.file_index,
    )


def test_relative_path_is_rejected(tmp_path):
    with pytest.raises(WindowsHandleIdentityError, match="absolute"):
        capture_windows_handle_identity(Path("relative.txt"))


def test_open_reparse_point_observes_link_object_when_supported(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"target")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")

    link_identity = capture_windows_handle_identity(
        link.absolute(),
        open_reparse_point=True,
    )
    target_identity = capture_windows_handle_identity(target.resolve())

    assert (
        link_identity.volume_serial_number,
        link_identity.file_index,
    ) != (
        target_identity.volume_serial_number,
        target_identity.file_index,
    )
