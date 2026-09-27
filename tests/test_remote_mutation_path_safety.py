from __future__ import annotations

import os

import pytest

from agent_control_plane.remote_mutation_composition import MutationCompositionRecord
from agent_control_plane.remote_mutation_path_safety import (
    MUTATION_PATH_SAFETY_SCHEMA_VERSION,
    MutationPathSafetyError,
    MutationPathSafetyRecord,
    inspect_repository_mutation_path,
)
from agent_control_plane.remote_mutation_transaction import MutationPlan

A = "a" * 64
B = "b" * 64
C = "c" * 64


def plan(*, operation_id="repo.write_text_file", path="docs/example.md"):
    parameters = (
        {"path": path, "content_sha256": C}
        if operation_id == "repo.write_text_file"
        else {"path": path, "prior_content_sha256": C}
    )
    return MutationPlan(
        request_id="req-path-1",
        authority_id="auth-path-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id=operation_id,
        parameters=parameters,
        precondition_sha256=A,
        rollback_sha256=B,
    )


def admitted_composition(p: MutationPlan) -> MutationCompositionRecord:
    return MutationCompositionRecord(
        request_id=p.request_id,
        authority_id=p.authority_id,
        operation_id=p.operation_id,
        resource_id=p.resource_id,
        plan_sha256=p.plan_sha256,
        admitted=True,
        reason="test admission",
    )


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    return root


def test_existing_write_target_is_admitted_without_execution(tmp_path):
    root = repo(tmp_path)
    target = root / "docs" / "example.md"
    target.write_text("before", encoding="utf-8")
    p = plan()

    record = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )

    assert record.schema_version == MUTATION_PATH_SAFETY_SCHEMA_VERSION
    assert record.admitted is True
    assert record.plan_sha256 == p.plan_sha256
    assert record.repository_boundary_verified is True
    assert record.symlink_safe is True
    assert record.repository_metadata_safe is True
    assert record.operation_shape_verified is True
    assert record.execution_enabled is False
    assert record.mutation_executed is False
    assert target.read_text(encoding="utf-8") == "before"


def test_new_write_target_with_existing_parent_is_admitted(tmp_path):
    root = repo(tmp_path)
    p = plan(path="docs/new.md")

    record = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )

    assert record.admitted is True
    assert not (root / "docs" / "new.md").exists()


def test_delete_requires_existing_regular_file(tmp_path):
    root = repo(tmp_path)
    p = plan(operation_id="repo.delete_file")
    blocked = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )
    assert blocked.admitted is False
    assert "operation shape" in blocked.reason

    target = root / "docs" / "example.md"
    target.write_text("keep", encoding="utf-8")
    allowed = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )
    assert allowed.admitted is True
    assert target.exists()


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../escape.txt",
        "docs/../escape.txt",
        "docs//x.txt",
        "docs/./x.txt",
        r"docs\x.txt",
        "C:/Windows/system.ini",
        "docs/file.txt:stream",
        "docs/trailing.",
        "docs/trailing ",
        " docs/leading.txt",
        "docs/CON",
        "docs/com1.txt",
    ],
)
def test_noncanonical_or_platform_ambiguous_paths_fail_closed(tmp_path, path):
    root = repo(tmp_path)
    p = plan(path=path)

    with pytest.raises(MutationPathSafetyError):
        inspect_repository_mutation_path(
            admitted_composition(p), p, repository_root=root
        )


@pytest.mark.parametrize("path", [".git/config", "nested/.GIT/HEAD"])
def test_git_metadata_paths_are_blocked(tmp_path, path):
    root = repo(tmp_path)
    (root / "nested").mkdir()
    p = plan(path=path)

    record = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )

    assert record.admitted is False
    assert record.repository_metadata_safe is False
    assert "repository metadata" in record.reason


def test_missing_parent_blocks_write(tmp_path):
    root = repo(tmp_path)
    p = plan(path="missing/example.md")

    record = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )

    assert record.admitted is False
    assert record.operation_shape_verified is False


def test_directory_target_blocks_write(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "example.md").mkdir()
    p = plan()

    record = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )

    assert record.admitted is False
    assert record.operation_shape_verified is False


def test_unadmitted_or_mismatched_composition_blocks_before_path_admission(tmp_path):
    root = repo(tmp_path)
    p = plan()
    composition = MutationCompositionRecord(
        request_id=p.request_id,
        authority_id=p.authority_id,
        operation_id=p.operation_id,
        resource_id=p.resource_id,
        plan_sha256=p.plan_sha256,
        admitted=False,
        reason="blocked upstream",
    )

    record = inspect_repository_mutation_path(
        composition, p, repository_root=root
    )

    assert record.admitted is False
    assert record.repository_boundary_verified is False
    assert "composition" in record.reason


def test_repository_root_must_be_absolute(tmp_path):
    p = plan()
    with pytest.raises(MutationPathSafetyError, match="absolute"):
        inspect_repository_mutation_path(
            admitted_composition(p), p, repository_root="relative/repo"
        )


def test_repository_marker_is_required(tmp_path):
    root = tmp_path / "not-a-repo"
    root.mkdir()
    (root / "docs").mkdir()
    p = plan()

    record = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )

    assert record.admitted is False
    assert ".git marker" in record.reason


def test_symlink_target_or_ancestor_is_blocked_when_supported(tmp_path):
    root = repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.md").write_text("outside", encoding="utf-8")
    link = root / "docs" / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    p = plan(path="docs/linked/victim.md")
    record = inspect_repository_mutation_path(
        admitted_composition(p), p, repository_root=root
    )

    assert record.admitted is False
    assert record.symlink_safe is False
    assert record.repository_boundary_verified is False
    assert (outside / "victim.md").read_text(encoding="utf-8") == "outside"


def test_path_safety_record_cannot_claim_execution(tmp_path):
    root = repo(tmp_path)
    p = plan()

    with pytest.raises(MutationPathSafetyError, match="cannot enable"):
        MutationPathSafetyRecord(
            request_id=p.request_id,
            resource_id=p.resource_id,
            operation_id=p.operation_id,
            plan_sha256=p.plan_sha256,
            requested_path="docs/example.md",
            repository_root=str(root),
            resolved_path=str(root / "docs" / "example.md"),
            admitted=True,
            reason="invalid",
            repository_boundary_verified=True,
            symlink_safe=True,
            repository_metadata_safe=True,
            operation_shape_verified=True,
            execution_enabled=True,
        )
