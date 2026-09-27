from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_control_plane.windows_handle_mutation import (
    WindowsHandleMutationError,
    replace_file_relative_to_held_parent,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only adapter")


def test_replaces_prepared_file_relative_to_held_parent(tmp_path: Path):
    target = tmp_path / "target.txt"
    prepared = tmp_path / "prepared.tmp"
    target.write_bytes(b"old")
    prepared.write_bytes(b"new")

    result = replace_file_relative_to_held_parent(
        prepared_file=prepared.resolve(),
        destination_parent=tmp_path.resolve(),
        destination_name="target.txt",
    )

    assert result.ntstatus == 0
    assert result.destination_name == "target.txt"
    assert target.read_bytes() == b"new"
    assert not prepared.exists()


def test_rejects_non_leaf_destination_name(tmp_path: Path):
    prepared = tmp_path / "prepared.tmp"
    prepared.write_bytes(b"new")
    with pytest.raises(WindowsHandleMutationError, match="leaf"):
        replace_file_relative_to_held_parent(
            prepared_file=prepared.resolve(),
            destination_parent=tmp_path.resolve(),
            destination_name=r"subdir\\target.txt",
        )
