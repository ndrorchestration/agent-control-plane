from __future__ import annotations

import hashlib
import os

import pytest

from agent_control_plane.remote_mutation_rollback_plan import (
    RepositoryRollbackPlan,
    RollbackAction,
)
from agent_control_plane.remote_mutation_rollback_revalidation import (
    ROLLBACK_REVALIDATION_SCHEMA_VERSION,
    RepositoryRollbackRevalidationRecord,
    RollbackRevalidationError,
    inspect_repository_rollback_state,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    return root


def plan(
    *,
    path="docs/example.md",
    expected_exists=True,
    expected_sha=C,
    action=RollbackAction.RESTORE_FILE_BYTES,
    desired_exists=True,
    desired_sha=B,
):
    return RepositoryRollbackPlan(
        rollback_request_id="rollback-req-1",
        rollback_authority_id="rollback-auth-1",
        rollback_transaction_id="rollback-tx-1",
        original_transaction_id="original-tx-1",
        original_request_id="original-req-1",
        resource_id="repo:test",
        original_operation_id="repo.write_text_file",
        original_plan_sha256=A,
        original_journal_state="failed",
        requested_path=path,
        rollback_descriptor_sha256=B,
        rollback_custody_ref="custody://rollback/test-1",
        action=action,
        expected_current_target_exists=expected_exists,
        expected_current_content_sha256=expected_sha if expected_exists else None,
        desired_target_exists=desired_exists,
        desired_content_sha256=desired_sha if desired_exists else None,
    )


def test_matching_existing_current_state_is_admitted_without_execution(tmp_path):
    root = repo(tmp_path)
    data = b"current"
    target = root / "docs" / "example.md"
    target.write_bytes(data)
    p = plan(expected_sha=sha(data))

    record = inspect_repository_rollback_state(p, repository_root=root)

    assert record.schema_version == ROLLBACK_REVALIDATION_SCHEMA_VERSION
    assert record.admitted is True
    assert record.current_state_verified is True
    assert record.observed_content_sha256 == sha(data)
    assert record.execution_enabled is False
    assert record.rollback_executed is False
    assert target.read_bytes() == data


def test_matching_absent_current_state_is_admitted_for_restore(tmp_path):
    root = repo(tmp_path)
    p = plan(expected_exists=False, expected_sha=None)

    record = inspect_repository_rollback_state(p, repository_root=root)

    assert record.admitted is True
    assert record.observed_target_exists is False
    assert record.current_state_verified is True


def test_concurrent_content_drift_blocks(tmp_path):
    root = repo(tmp_path)
    target = root / "docs" / "example.md"
    target.write_bytes(b"changed")
    p = plan(expected_sha=sha(b"expected"))

    record = inspect_repository_rollback_state(p, repository_root=root)

    assert record.admitted is False
    assert record.current_state_verified is False
    assert "current state" in record.reason


def test_concurrent_creation_blocks_expected_absence(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "example.md").write_bytes(b"new-concurrent-content")
    p = plan(expected_exists=False, expected_sha=None)

    record = inspect_repository_rollback_state(p, repository_root=root)

    assert record.admitted is False
    assert record.current_state_verified is False


def test_concurrent_deletion_blocks_expected_presence(tmp_path):
    root = repo(tmp_path)
    p = plan(expected_exists=True, expected_sha=sha(b"expected"))

    record = inspect_repository_rollback_state(p, repository_root=root)

    assert record.admitted is False
    assert record.current_state_verified is False


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.md",
        "../escape.md",
        "docs/../escape.md",
        "docs//example.md",
        r"docs\example.md",
        "C:/Windows/system.ini",
        "docs/file.txt:stream",
        "docs/trailing.",
        " docs/leading.md",
        "docs/CON",
    ],
)
def test_noncanonical_paths_fail_closed(tmp_path, path):
    root = repo(tmp_path)
    p = plan(path=path)
    with pytest.raises(RollbackRevalidationError):
        inspect_repository_rollback_state(p, repository_root=root)


def test_git_metadata_path_is_blocked(tmp_path):
    root = repo(tmp_path)
    p = plan(path=".git/config", expected_exists=False, expected_sha=None)
    record = inspect_repository_rollback_state(p, repository_root=root)
    assert record.admitted is False
    assert record.repository_metadata_safe is False


def test_missing_parent_blocks(tmp_path):
    root = repo(tmp_path)
    p = plan(path="missing/example.md", expected_exists=False, expected_sha=None)
    record = inspect_repository_rollback_state(p, repository_root=root)
    assert record.admitted is False
    assert record.operation_shape_verified is False


def test_symlink_or_reparse_ancestor_is_blocked_when_supported(tmp_path):
    root = repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "docs" / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    p = plan(path="docs/linked/file.md", expected_exists=False, expected_sha=None)
    record = inspect_repository_rollback_state(p, repository_root=root)
    assert record.admitted is False
    assert record.link_safe is False
    assert record.repository_boundary_verified is False


def test_existing_hardlink_target_is_blocked(tmp_path):
    root = repo(tmp_path)
    target = root / "docs" / "example.md"
    alias = root / "docs" / "alias.md"
    data = b"current"
    target.write_bytes(data)
    try:
        os.link(target, alias)
    except (OSError, NotImplementedError):
        pytest.skip("hardlink creation unavailable")
    p = plan(expected_sha=sha(data))
    record = inspect_repository_rollback_state(p, repository_root=root)
    assert record.admitted is False
    assert record.hardlink_safe is False
    assert "hardlink safety" in record.reason


def test_relative_repository_root_is_rejected(tmp_path):
    with pytest.raises(RollbackRevalidationError, match="absolute"):
        inspect_repository_rollback_state(plan(), repository_root="relative/repo")


def test_missing_git_marker_blocks(tmp_path):
    root = tmp_path / "not-repo"
    root.mkdir()
    (root / "docs").mkdir()
    record = inspect_repository_rollback_state(
        plan(expected_exists=False, expected_sha=None),
        repository_root=root,
    )
    assert record.admitted is False


def test_revalidation_record_cannot_claim_execution(tmp_path):
    root = repo(tmp_path)
    with pytest.raises(RollbackRevalidationError, match="cannot enable"):
        RepositoryRollbackRevalidationRecord(
            rollback_transaction_id="rollback-tx",
            rollback_plan_sha256=A,
            resource_id="repo:test",
            requested_path="docs/example.md",
            repository_root=str(root),
            resolved_path=str(root / "docs" / "example.md"),
            admitted=True,
            reason="invalid",
            repository_boundary_verified=True,
            repository_metadata_safe=True,
            link_safe=True,
            hardlink_safe=True,
            operation_shape_verified=True,
            current_state_verified=True,
            observed_target_exists=True,
            observed_content_sha256=C,
            execution_enabled=True,
        )
