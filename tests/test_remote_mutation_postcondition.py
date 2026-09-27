from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_control_plane.remote_mutation_path_safety import MutationPathSafetyRecord
from agent_control_plane.remote_mutation_postcondition import (
    MUTATION_POSTCONDITION_SCHEMA_VERSION,
    MutationPostconditionError,
    MutationPostconditionRecord,
    verify_repository_mutation_postcondition,
)
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_transaction import MutationPlan

A = "a" * 64
B = "b" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    return root


def write_plan(content: bytes, *, path="docs/example.md", prior=b"before"):
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path=path,
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=sha(prior),
        prior_content_size=len(prior),
    )
    plan = MutationPlan(
        request_id="req-post-1",
        authority_id="auth-post-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={"path": path, "content_sha256": sha(content)},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    return plan, descriptor


def delete_plan(prior: bytes, *, path="docs/example.md"):
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.delete_file",
        path=path,
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=sha(prior),
        prior_content_size=len(prior),
    )
    plan = MutationPlan(
        request_id="req-post-2",
        authority_id="auth-post-2",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.delete_file",
        parameters={"path": path, "prior_content_sha256": sha(prior)},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    return plan, descriptor


def upstream(plan: MutationPlan, descriptor: RollbackMaterialDescriptor, root: Path):
    path_record = MutationPathSafetyRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"],
        repository_root=str(root),
        resolved_path=str(root / plan.parameters["path"]),
        admitted=True,
        reason="safe before external execution",
        repository_boundary_verified=True,
        symlink_safe=True,
        repository_metadata_safe=True,
        operation_shape_verified=True,
        target_exists=True,
    )
    custody = RollbackCustodyAdmissionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://operator-local/rollback-post",
        admitted=True,
        reason="custody verified",
        readback_verified=True,
    )
    return path_record, custody


def test_write_postcondition_verifies_exact_content(tmp_path):
    root = repo(tmp_path)
    expected = b"after"
    plan, descriptor = write_plan(expected)
    target = root / "docs" / "example.md"
    target.write_bytes(expected)
    path, custody = upstream(plan, descriptor, root)
    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )
    assert record.schema_version == MUTATION_POSTCONDITION_SCHEMA_VERSION
    assert record.postcondition_verified is True
    assert record.path_revalidated is True
    assert record.target_exists is True
    assert record.observed_content_sha256 == sha(expected)
    assert record.rollback_descriptor_sha256 == plan.rollback_sha256
    assert record.rollback_custody_ref == custody.custody_ref
    assert record.execution_enabled is False
    assert record.acp_mutation_executed is False


def test_write_postcondition_blocks_wrong_content(tmp_path):
    root = repo(tmp_path)
    plan, descriptor = write_plan(b"expected")
    (root / "docs" / "example.md").write_bytes(b"unexpected")
    path, custody = upstream(plan, descriptor, root)
    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )
    assert record.postcondition_verified is False
    assert "write_postcondition" in record.reason


def test_write_postcondition_blocks_missing_target(tmp_path):
    root = repo(tmp_path)
    plan, descriptor = write_plan(b"expected")
    path, custody = upstream(plan, descriptor, root)
    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )
    assert record.postcondition_verified is False
    assert record.target_exists is False


def test_delete_postcondition_verifies_absence(tmp_path):
    root = repo(tmp_path)
    plan, descriptor = delete_plan(b"before")
    path, custody = upstream(plan, descriptor, root)
    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )
    assert record.postcondition_verified is True
    assert record.target_exists is False
    assert record.observed_content_sha256 is None


def test_delete_postcondition_blocks_surviving_file_and_reports_hash(tmp_path):
    root = repo(tmp_path)
    prior = b"before"
    plan, descriptor = delete_plan(prior)
    target = root / "docs" / "example.md"
    target.write_bytes(prior)
    path, custody = upstream(plan, descriptor, root)
    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )
    assert record.postcondition_verified is False
    assert record.target_exists is True
    assert record.observed_content_sha256 == sha(prior)
    assert "delete_postcondition" in record.reason


def test_unadmitted_rollback_custody_blocks_even_if_state_matches(tmp_path):
    root = repo(tmp_path)
    expected = b"after"
    plan, descriptor = write_plan(expected)
    (root / "docs" / "example.md").write_bytes(expected)
    path, custody = upstream(plan, descriptor, root)
    custody = RollbackCustodyAdmissionRecord(
        request_id=custody.request_id,
        resource_id=custody.resource_id,
        operation_id=custody.operation_id,
        plan_sha256=custody.plan_sha256,
        descriptor_sha256=custody.descriptor_sha256,
        custody_ref=custody.custody_ref,
        admitted=False,
        reason="blocked",
        readback_verified=True,
    )
    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )
    assert record.postcondition_verified is False
    assert "rollback_custody" in record.reason


def test_plan_identity_drift_blocks(tmp_path):
    root = repo(tmp_path)
    expected = b"after"
    plan, descriptor = write_plan(expected)
    (root / "docs" / "example.md").write_bytes(expected)
    path, custody = upstream(plan, descriptor, root)
    other, _ = write_plan(expected, path="docs/other.md")
    record = verify_repository_mutation_postcondition(
        other, path, custody, repository_root=root
    )
    assert record.postcondition_verified is False
    assert "path_safety" in record.reason
    assert "rollback_custody" in record.reason


def test_repository_root_must_be_absolute(tmp_path):
    plan, descriptor = write_plan(b"after")
    root = repo(tmp_path)
    path, custody = upstream(plan, descriptor, root)
    with pytest.raises(MutationPostconditionError, match="absolute"):
        verify_repository_mutation_postcondition(
            plan, path, custody, repository_root="relative/repo"
        )


def test_repository_marker_is_revalidated(tmp_path):
    root = tmp_path / "not-repo"
    root.mkdir()
    (root / "docs").mkdir()
    expected = b"after"
    plan, descriptor = write_plan(expected)
    (root / "docs" / "example.md").write_bytes(expected)
    path, custody = upstream(plan, descriptor, root)
    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )
    assert record.postcondition_verified is False
    assert "repository_root" in record.reason


def test_postcondition_record_cannot_claim_acp_execution(tmp_path):
    root = repo(tmp_path)
    with pytest.raises(MutationPostconditionError, match="cannot enable"):
        MutationPostconditionRecord(
            request_id="req",
            resource_id="repo",
            operation_id="repo.write_text_file",
            plan_sha256=A,
            requested_path="docs/example.md",
            repository_root=str(root),
            resolved_path=str(root / "docs" / "example.md"),
            rollback_descriptor_sha256=B,
            rollback_custody_ref="custody://test",
            target_exists=True,
            observed_content_sha256=B,
            path_revalidated=True,
            postcondition_verified=True,
            reason="invalid",
            acp_mutation_executed=True,
        )


def test_repository_root_substitution_blocks(tmp_path):
    root = repo(tmp_path)
    other_parent = tmp_path / "other"
    other_parent.mkdir()
    other = repo(other_parent)
    expected = b"after"
    plan, descriptor = write_plan(expected)
    (root / "docs" / "example.md").write_bytes(expected)
    (other / "docs" / "example.md").write_bytes(expected)
    path, custody = upstream(plan, descriptor, root)

    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=other
    )

    assert record.postcondition_verified is False
    assert "path_safety.repository_root" in record.reason


def test_resolved_target_substitution_blocks(tmp_path):
    root = repo(tmp_path)
    expected = b"after"
    plan, descriptor = write_plan(expected)
    (root / "docs" / "example.md").write_bytes(expected)
    path, custody = upstream(plan, descriptor, root)
    path = MutationPathSafetyRecord(
        **{
            **path.__dict__,
            "resolved_path": str(root / "docs" / "other.md"),
        }
    )

    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )

    assert record.postcondition_verified is False
    assert "path_safety.resolved_path" in record.reason


def test_rollback_descriptor_substitution_blocks(tmp_path):
    root = repo(tmp_path)
    expected = b"after"
    plan, descriptor = write_plan(expected)
    (root / "docs" / "example.md").write_bytes(expected)
    path, custody = upstream(plan, descriptor, root)
    custody = RollbackCustodyAdmissionRecord(
        request_id=custody.request_id,
        resource_id=custody.resource_id,
        operation_id=custody.operation_id,
        plan_sha256=custody.plan_sha256,
        descriptor_sha256="f" * 64,
        custody_ref=custody.custody_ref,
        admitted=True,
        reason="fabricated",
        readback_verified=True,
    )

    record = verify_repository_mutation_postcondition(
        plan, path, custody, repository_root=root
    )

    assert record.postcondition_verified is False
    assert "rollback_custody" in record.reason
