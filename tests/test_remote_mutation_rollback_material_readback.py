from __future__ import annotations

import hashlib

import pytest

from agent_control_plane.remote_mutation_rollback_authorization import (
    RepositoryRollbackAuthorization,
)
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_rollback_material_readback import (
    ROLLBACK_MATERIAL_READBACK_SCHEMA_VERSION,
    RollbackMaterialReadbackError,
    RollbackMaterialReadbackRecord,
    verify_rollback_material_readback,
)
from agent_control_plane.remote_mutation_rollback_plan import (
    RepositoryRollbackPlan,
    RollbackAction,
)

A = "a" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def restore_fixture(*, consumed=False):
    prior = b"prior-state"
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=sha(prior),
        prior_content_size=len(prior),
    )
    plan = RepositoryRollbackPlan(
        rollback_request_id="rb-req",
        rollback_authority_id="rb-authority",
        rollback_transaction_id="rb-tx",
        original_transaction_id="orig-tx",
        original_request_id="orig-req",
        resource_id="repo:test",
        original_operation_id="repo.write_text_file",
        original_plan_sha256=A,
        original_journal_state="failed",
        requested_path="docs/example.md",
        rollback_descriptor_sha256=descriptor.descriptor_sha256,
        rollback_custody_ref="custody://rollback/material-1",
        action=RollbackAction.RESTORE_FILE_BYTES,
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(b"current"),
        desired_target_exists=True,
        desired_content_sha256=sha(prior),
    )
    auth = RepositoryRollbackAuthorization(
        authorization_id="rb-authz",
        rollback_executor_id="rb-executor:test",
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_request_id=plan.rollback_request_id,
        rollback_authority_id=plan.rollback_authority_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        original_transaction_id=plan.original_transaction_id,
        original_plan_sha256=plan.original_plan_sha256,
        rollback_descriptor_sha256=plan.rollback_descriptor_sha256,
        rollback_custody_ref=plan.rollback_custody_ref,
        issued_at="2026-09-27T15:00:00Z",
        expires_at="2026-09-27T15:05:00Z",
        consumed_at="2026-09-27T15:01:00Z" if consumed else None,
    )
    return prior, descriptor, plan, auth


def delete_created_fixture():
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/new.md",
        mode=RollbackMode.DELETE_CREATED_FILE,
    )
    plan = RepositoryRollbackPlan(
        rollback_request_id="rb-req-delete",
        rollback_authority_id="rb-authority",
        rollback_transaction_id="rb-tx-delete",
        original_transaction_id="orig-tx",
        original_request_id="orig-req",
        resource_id="repo:test",
        original_operation_id="repo.write_text_file",
        original_plan_sha256=A,
        original_journal_state="failed",
        requested_path="docs/new.md",
        rollback_descriptor_sha256=descriptor.descriptor_sha256,
        rollback_custody_ref="custody://rollback/material-delete",
        action=RollbackAction.DELETE_CREATED_FILE,
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(b"created"),
        desired_target_exists=False,
        desired_content_sha256=None,
    )
    auth = RepositoryRollbackAuthorization(
        authorization_id="rb-authz-delete",
        rollback_executor_id="rb-executor:test",
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_request_id=plan.rollback_request_id,
        rollback_authority_id=plan.rollback_authority_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        original_transaction_id=plan.original_transaction_id,
        original_plan_sha256=plan.original_plan_sha256,
        rollback_descriptor_sha256=plan.rollback_descriptor_sha256,
        rollback_custody_ref=plan.rollback_custody_ref,
        issued_at="2026-09-27T15:00:00Z",
        expires_at="2026-09-27T15:05:00Z",
    )
    return descriptor, plan, auth


def test_restore_bytes_are_verified_without_consuming_authorization():
    prior, descriptor, plan, auth = restore_fixture()
    record = verify_rollback_material_readback(
        plan, descriptor, auth, material=prior
    )
    assert record.schema_version == ROLLBACK_MATERIAL_READBACK_SCHEMA_VERSION
    assert record.admitted is True
    assert record.material_required is True
    assert record.observed_material_sha256 == sha(prior)
    assert record.observed_material_size == len(prior)
    assert record.authorization_consumed is False
    assert record.execution_enabled is False
    assert record.rollback_executed is False
    assert auth.consumed is False


def test_restore_missing_material_blocks():
    _, descriptor, plan, auth = restore_fixture()
    record = verify_rollback_material_readback(
        plan, descriptor, auth, material=None
    )
    assert record.admitted is False
    assert "material.missing" in record.reason


def test_restore_wrong_hash_blocks():
    _, descriptor, plan, auth = restore_fixture()
    record = verify_rollback_material_readback(
        plan, descriptor, auth, material=b"wrong"
    )
    assert record.admitted is False
    assert "material.sha256" in record.reason


def test_restore_wrong_size_blocks_even_if_descriptor_hash_is_forged():
    prior, descriptor, plan, auth = restore_fixture()
    forged = RollbackMaterialDescriptor(
        operation_id=descriptor.operation_id,
        path=descriptor.path,
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=sha(prior),
        prior_content_size=len(prior) + 1,
    )
    record = verify_rollback_material_readback(
        plan, forged, auth, material=prior
    )
    assert record.admitted is False
    assert "descriptor.plan_identity" in record.reason or "material.size" in record.reason


def test_delete_created_requires_no_material_bytes():
    descriptor, plan, auth = delete_created_fixture()
    record = verify_rollback_material_readback(
        plan, descriptor, auth, material=None
    )
    assert record.admitted is True
    assert record.material_required is False
    assert record.observed_material_sha256 is None


def test_delete_created_rejects_unexpected_material_bytes():
    descriptor, plan, auth = delete_created_fixture()
    record = verify_rollback_material_readback(
        plan, descriptor, auth, material=b"unexpected"
    )
    assert record.admitted is False
    assert "material.unexpected" in record.reason


def test_consumed_authorization_blocks_readback_admission():
    prior, descriptor, plan, auth = restore_fixture(consumed=True)
    record = verify_rollback_material_readback(
        plan, descriptor, auth, material=prior
    )
    assert record.admitted is False
    assert record.authorization_consumed is True
    assert "authorization.consumed" in record.reason


def test_descriptor_identity_drift_blocks():
    prior, descriptor, plan, auth = restore_fixture()
    other = RollbackMaterialDescriptor(
        operation_id=descriptor.operation_id,
        path="docs/other.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=descriptor.prior_content_sha256,
        prior_content_size=descriptor.prior_content_size,
    )
    record = verify_rollback_material_readback(
        plan, other, auth, material=prior
    )
    assert record.admitted is False
    assert "descriptor.plan_identity" in record.reason


def test_authorization_plan_identity_drift_blocks():
    prior, descriptor, plan, auth = restore_fixture()
    bad = RepositoryRollbackAuthorization(
        authorization_id=auth.authorization_id,
        rollback_executor_id=auth.rollback_executor_id,
        rollback_transaction_id=auth.rollback_transaction_id,
        rollback_request_id=auth.rollback_request_id,
        rollback_authority_id=auth.rollback_authority_id,
        rollback_plan_sha256=A,
        original_transaction_id=auth.original_transaction_id,
        original_plan_sha256=auth.original_plan_sha256,
        rollback_descriptor_sha256=auth.rollback_descriptor_sha256,
        rollback_custody_ref=auth.rollback_custody_ref,
        issued_at=auth.issued_at,
        expires_at=auth.expires_at,
    )
    record = verify_rollback_material_readback(
        plan, descriptor, bad, material=prior
    )
    assert record.admitted is False
    assert "authorization.plan_identity" in record.reason


def test_readback_record_cannot_claim_execution():
    with pytest.raises(RollbackMaterialReadbackError, match="cannot enable"):
        RollbackMaterialReadbackRecord(
            authorization_id="auth",
            rollback_transaction_id="tx",
            rollback_plan_sha256=A,
            rollback_descriptor_sha256=A,
            rollback_custody_ref="custody://x",
            action=RollbackAction.RESTORE_FILE_BYTES,
            material_required=True,
            observed_material_sha256=A,
            observed_material_size=1,
            admitted=True,
            reason="invalid",
            authorization_consumed=False,
            execution_enabled=True,
        )
