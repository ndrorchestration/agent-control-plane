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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    return root


def build(
    root: Path,
    *,
    operation_id: str = "repo.write_text_file",
    target_existed_before: bool = True,
):
    target = root / "docs" / "example.md"
    prior = b"before\n"
    after = b"after\n"

    if operation_id == "repo.write_text_file":
        if target_existed_before:
            target.write_bytes(prior)
            descriptor = RollbackMaterialDescriptor(
                operation_id=operation_id,
                path="docs/example.md",
                mode=RollbackMode.RESTORE_FILE_BYTES,
                prior_content_sha256=sha(prior),
                prior_content_size=len(prior),
            )
        else:
            descriptor = RollbackMaterialDescriptor(
                operation_id=operation_id,
                path="docs/example.md",
                mode=RollbackMode.DELETE_CREATED_FILE,
            )
        parameters = {
            "path": "docs/example.md",
            "content_sha256": sha(after),
        }
    else:
        target.write_bytes(prior)
        descriptor = RollbackMaterialDescriptor(
            operation_id=operation_id,
            path="docs/example.md",
            mode=RollbackMode.RESTORE_FILE_BYTES,
            prior_content_sha256=sha(prior),
            prior_content_size=len(prior),
        )
        parameters = {
            "path": "docs/example.md",
            "prior_content_sha256": sha(prior),
        }

    plan = MutationPlan(
        request_id="req-post",
        authority_id="auth-post",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id=operation_id,
        parameters=parameters,
        precondition_sha256="a" * 64,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    path_safety = MutationPathSafetyRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"],
        repository_root=str(root.resolve()),
        resolved_path=str(target.resolve(strict=False)),
        admitted=True,
        reason="safe",
        repository_boundary_verified=True,
        symlink_safe=True,
        repository_metadata_safe=True,
        operation_shape_verified=True,
        target_exists=target_existed_before,
    )
    custody = RollbackCustodyAdmissionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://test/postcondition",
        admitted=True,
        reason="verified",
        readback_verified=True,
    )
    return plan, path_safety, custody, target, after


@pytest.mark.parametrize("target_existed_before", [True, False])
def test_write_postcondition_verifies_exact_content(tmp_path, target_existed_before):
    root = make_root(tmp_path)
    plan, path_safety, custody, target, after = build(
        root, target_existed_before=target_existed_before
    )
    target.write_bytes(after)

    record = verify_repository_mutation_postcondition(
        plan,
        path_safety,
        custody,
        repository_root=root,
    )

    assert record.schema_version == MUTATION_POSTCONDITION_SCHEMA_VERSION
    assert record.postcondition_verified is True
    assert record.path_revalidated is True
    assert record.observed_content_sha256 == sha(after)
    assert record.rollback_descriptor_sha256 == plan.rollback_sha256
    assert record.rollback_custody_ref == custody.custody_ref
    assert record.execution_enabled is False
    assert record.mutation_executed is False


def test_delete_postcondition_verifies_target_absence(tmp_path):
    root = make_root(tmp_path)
    plan, path_safety, custody, target, _ = build(
        root,
        operation_id="repo.delete_file",
    )
    target.unlink()

    record = verify_repository_mutation_postcondition(
        plan, path_safety, custody, repository_root=root
    )

    assert record.postcondition_verified is True
    assert record.target_exists is False
    assert record.observed_content_sha256 is None


def test_wrong_write_content_blocks(tmp_path):
    root = make_root(tmp_path)
    plan, path_safety, custody, target, _ = build(root)
    target.write_bytes(b"wrong\n")

    record = verify_repository_mutation_postcondition(
        plan, path_safety, custody, repository_root=root
    )

    assert record.postcondition_verified is False
    assert "write_postcondition" in record.reason


def test_delete_target_still_present_blocks(tmp_path):
    root = make_root(tmp_path)
    plan, path_safety, custody, _, _ = build(
        root,
        operation_id="repo.delete_file",
    )

    record = verify_repository_mutation_postcondition(
        plan, path_safety, custody, repository_root=root
    )

    assert record.postcondition_verified is False
    assert "delete_postcondition" in record.reason


def test_repository_root_substitution_blocks(tmp_path):
    root = make_root(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / ".git").mkdir()
    (other / "docs").mkdir()
    plan, path_safety, custody, _, after = build(root)
    (other / "docs" / "example.md").write_bytes(after)

    record = verify_repository_mutation_postcondition(
        plan, path_safety, custody, repository_root=other
    )

    assert record.postcondition_verified is False
    assert "path_safety.repository_root" in record.reason


def test_resolved_target_substitution_blocks(tmp_path):
    root = make_root(tmp_path)
    plan, path_safety, custody, target, after = build(root)
    target.write_bytes(after)
    bad_path = MutationPathSafetyRecord(
        **{
            **path_safety.__dict__,
            "resolved_path": str(root / "docs" / "other.md"),
        }
    )

    record = verify_repository_mutation_postcondition(
        plan, bad_path, custody, repository_root=root
    )

    assert record.postcondition_verified is False
    assert "path_safety.resolved_path" in record.reason


def test_rollback_descriptor_substitution_blocks(tmp_path):
    root = make_root(tmp_path)
    plan, path_safety, custody, target, after = build(root)
    target.write_bytes(after)
    bad_custody = RollbackCustodyAdmissionRecord(
        request_id=custody.request_id,
        resource_id=custody.resource_id,
        operation_id=custody.operation_id,
        plan_sha256=custody.plan_sha256,
        descriptor_sha256="f" * 64,
        custody_ref=custody.custody_ref,
        admitted=True,
        reason="fabricated mismatch",
        readback_verified=True,
    )

    record = verify_repository_mutation_postcondition(
        plan, path_safety, bad_custody, repository_root=root
    )

    assert record.postcondition_verified is False
    assert "rollback_custody" in record.reason


def test_symlink_postcondition_fails_closed_when_supported(tmp_path):
    root = make_root(tmp_path)
    plan, path_safety, custody, target, after = build(root)
    outside = tmp_path / "outside.md"
    outside.write_bytes(after)
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")

    record = verify_repository_mutation_postcondition(
        plan, path_safety, custody, repository_root=root
    )

    assert record.postcondition_verified is False
    assert "path_revalidation" in record.reason


def test_record_cannot_claim_mutation_execution():
    with pytest.raises(MutationPostconditionError, match="cannot enable"):
        MutationPostconditionRecord(
            request_id="req",
            resource_id="repo",
            operation_id="repo.write_text_file",
            plan_sha256="a" * 64,
            requested_path="docs/example.md",
            repository_root="C:/repo",
            resolved_path="C:/repo/docs/example.md",
            rollback_descriptor_sha256="b" * 64,
            rollback_custody_ref="custody://test",
            target_exists=True,
            observed_content_sha256="c" * 64,
            path_revalidated=True,
            postcondition_verified=True,
            reason="invalid",
            mutation_executed=True,
        )
