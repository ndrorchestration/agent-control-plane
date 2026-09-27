from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.remote_mutation_composition import MutationCompositionRecord
from agent_control_plane.remote_mutation_path_safety import MutationPathSafetyRecord
from agent_control_plane.remote_mutation_rollback_custody import (
    ROLLBACK_CUSTODY_SCHEMA_VERSION,
    RollbackCustodyAdmissionRecord,
    RollbackCustodyError,
    RollbackCustodyEvidence,
    RollbackMaterialDescriptor,
    RollbackMode,
    admit_rollback_custody,
)
from agent_control_plane.remote_mutation_transaction import (
    MutationPlan,
    MutationTransactionReceipt,
    MutationTransactionState,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


def descriptor(*, operation_id="repo.write_text_file", path="docs/example.md",
               mode=RollbackMode.RESTORE_FILE_BYTES,
               prior_content_sha256=B, prior_content_size=6):
    return RollbackMaterialDescriptor(
        operation_id=operation_id,
        path=path,
        mode=mode,
        prior_content_sha256=prior_content_sha256,
        prior_content_size=prior_content_size,
    )


def plan_for(d: RollbackMaterialDescriptor, *, operation_id=None):
    op = operation_id or d.operation_id
    parameters = (
        {"path": d.path, "content_sha256": C}
        if op == "repo.write_text_file"
        else {"path": d.path, "prior_content_sha256": d.prior_content_sha256}
    )
    return MutationPlan(
        request_id="req-rb-1",
        authority_id="auth-rb-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id=op,
        parameters=parameters,
        precondition_sha256=A,
        rollback_sha256=d.descriptor_sha256,
    )


def upstream(p: MutationPlan, *, target_exists=True):
    composition = MutationCompositionRecord(
        request_id=p.request_id,
        authority_id=p.authority_id,
        operation_id=p.operation_id,
        resource_id=p.resource_id,
        plan_sha256=p.plan_sha256,
        admitted=True,
        reason="upstream exact composition",
    )
    transaction = MutationTransactionReceipt(
        request_id=p.request_id,
        authority_id=p.authority_id,
        operation_id=p.operation_id,
        plan_sha256=p.plan_sha256,
        precondition_sha256=p.precondition_sha256,
        rollback_sha256=p.rollback_sha256,
        state=MutationTransactionState.PRECONDITIONS_VERIFIED,
        preconditions_verified=True,
        rollback_available=True,
    )
    path_safety = MutationPathSafetyRecord(
        request_id=p.request_id,
        resource_id=p.resource_id,
        operation_id=p.operation_id,
        plan_sha256=p.plan_sha256,
        requested_path=p.parameters["path"],
        repository_root=str(Path.cwd()),
        resolved_path=str(Path.cwd() / p.parameters["path"]),
        admitted=True,
        reason="safe",
        repository_boundary_verified=True,
        symlink_safe=True,
        repository_metadata_safe=True,
        operation_shape_verified=True,
        target_exists=target_exists,
    )
    return composition, transaction, path_safety


def evidence(p, d, *, object_sha=None, readback_sha=None):
    expected = (
        d.prior_content_sha256
        if d.mode is RollbackMode.RESTORE_FILE_BYTES
        else d.descriptor_sha256
    )
    return RollbackCustodyEvidence(
        request_id=p.request_id,
        resource_id=p.resource_id,
        operation_id=p.operation_id,
        plan_sha256=p.plan_sha256,
        descriptor_sha256=d.descriptor_sha256,
        custody_ref="custody://operator-local/rollback-1",
        custody_object_sha256=object_sha or expected,
        observed_readback_sha256=readback_sha or expected,
    )


def test_existing_write_requires_restore_bytes_and_admits_verified_custody():
    d = descriptor()
    p = plan_for(d)
    c, tx, path = upstream(p, target_exists=True)

    record = admit_rollback_custody(c, p, tx, path, d, evidence(p, d))

    assert record.schema_version == ROLLBACK_CUSTODY_SCHEMA_VERSION
    assert record.admitted is True
    assert record.readback_verified is True
    assert record.descriptor_sha256 == p.rollback_sha256
    assert record.execution_enabled is False
    assert record.mutation_executed is False


def test_new_file_write_requires_delete_created_file_descriptor():
    d = descriptor(
        mode=RollbackMode.DELETE_CREATED_FILE,
        prior_content_sha256=None,
        prior_content_size=None,
    )
    p = plan_for(d)
    c, tx, path = upstream(p, target_exists=False)

    record = admit_rollback_custody(c, p, tx, path, d, evidence(p, d))

    assert record.admitted is True
    assert record.readback_verified is True


def test_existing_write_rejects_delete_created_file_mode():
    d = descriptor(
        mode=RollbackMode.DELETE_CREATED_FILE,
        prior_content_sha256=None,
        prior_content_size=None,
    )
    p = plan_for(d)
    c, tx, path = upstream(p, target_exists=True)

    record = admit_rollback_custody(c, p, tx, path, d, evidence(p, d))
    assert record.admitted is False
    assert "descriptor.mode" in record.reason


def test_new_write_rejects_restore_bytes_mode():
    d = descriptor()
    p = plan_for(d)
    c, tx, path = upstream(p, target_exists=False)

    record = admit_rollback_custody(c, p, tx, path, d, evidence(p, d))
    assert record.admitted is False
    assert "descriptor.mode" in record.reason


def test_delete_requires_restore_bytes_bound_to_prior_content_hash():
    d = descriptor(operation_id="repo.delete_file")
    p = plan_for(d)
    c, tx, path = upstream(p, target_exists=True)

    record = admit_rollback_custody(c, p, tx, path, d, evidence(p, d))
    assert record.admitted is True

    bad_d = descriptor(operation_id="repo.delete_file", prior_content_sha256=C)
    bad_p = MutationPlan(
        request_id=p.request_id,
        authority_id=p.authority_id,
        resource_id=p.resource_id,
        resource_type=p.resource_type,
        operation_id=p.operation_id,
        parameters={"path": d.path, "prior_content_sha256": B},
        precondition_sha256=A,
        rollback_sha256=bad_d.descriptor_sha256,
    )
    c2, tx2, path2 = upstream(bad_p, target_exists=True)
    rec2 = admit_rollback_custody(
        c2, bad_p, tx2, path2, bad_d, evidence(bad_p, bad_d)
    )
    assert rec2.admitted is False
    assert "descriptor.prior_content_sha256" in rec2.reason


def test_descriptor_hash_is_deterministic_and_plan_bound():
    d1 = descriptor()
    d2 = descriptor()
    assert d1.canonical_bytes() == d2.canonical_bytes()
    assert d1.descriptor_sha256 == d2.descriptor_sha256
    assert plan_for(d1).rollback_sha256 == d1.descriptor_sha256


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": RollbackMode.RESTORE_FILE_BYTES, "prior_content_sha256": None},
        {"mode": RollbackMode.RESTORE_FILE_BYTES, "prior_content_size": -1},
        {
            "mode": RollbackMode.DELETE_CREATED_FILE,
            "prior_content_sha256": B,
            "prior_content_size": 1,
        },
    ],
)
def test_descriptor_rejects_impossible_material_shape(kwargs):
    values = {
        "mode": RollbackMode.RESTORE_FILE_BYTES,
        "prior_content_sha256": B,
        "prior_content_size": 6,
    }
    values.update(kwargs)
    with pytest.raises(RollbackCustodyError):
        descriptor(**values)


def test_descriptor_hash_mismatch_blocks():
    d = descriptor()
    p = plan_for(d)
    c, tx, path = upstream(p)
    other = descriptor(path="docs/other.md")

    record = admit_rollback_custody(c, p, tx, path, other, evidence(p, other))
    assert record.admitted is False
    assert "descriptor" in record.reason


def test_custody_object_hash_mismatch_blocks():
    d = descriptor()
    p = plan_for(d)
    c, tx, path = upstream(p)

    record = admit_rollback_custody(
        c, p, tx, path, d, evidence(p, d, object_sha=C, readback_sha=C)
    )
    assert record.admitted is False
    assert "custody_object_sha256" in record.reason


def test_readback_mismatch_blocks():
    d = descriptor()
    p = plan_for(d)
    c, tx, path = upstream(p)

    record = admit_rollback_custody(
        c, p, tx, path, d, evidence(p, d, readback_sha=C)
    )
    assert record.admitted is False
    assert record.readback_verified is False
    assert "readback_sha256" in record.reason


def test_unadmitted_upstream_composition_blocks():
    d = descriptor()
    p = plan_for(d)
    _, tx, path = upstream(p)
    composition = MutationCompositionRecord(
        request_id=p.request_id,
        authority_id=p.authority_id,
        operation_id=p.operation_id,
        resource_id=p.resource_id,
        plan_sha256=p.plan_sha256,
        admitted=False,
        reason="blocked",
    )

    record = admit_rollback_custody(
        composition, p, tx, path, d, evidence(p, d)
    )
    assert record.admitted is False
    assert "composition.admitted" in record.reason


def test_unadmitted_path_safety_blocks():
    d = descriptor()
    p = plan_for(d)
    c, tx, path = upstream(p)
    path = MutationPathSafetyRecord(
        request_id=path.request_id,
        resource_id=path.resource_id,
        operation_id=path.operation_id,
        plan_sha256=path.plan_sha256,
        requested_path=path.requested_path,
        repository_root=path.repository_root,
        resolved_path=path.resolved_path,
        admitted=False,
        reason="blocked",
        repository_boundary_verified=False,
        symlink_safe=False,
        repository_metadata_safe=False,
        operation_shape_verified=False,
        target_exists=True,
    )

    record = admit_rollback_custody(c, p, tx, path, d, evidence(p, d))
    assert record.admitted is False
    assert "path_safety" in record.reason


def test_custody_record_cannot_claim_execution():
    with pytest.raises(RollbackCustodyError, match="cannot enable"):
        RollbackCustodyAdmissionRecord(
            request_id="req",
            resource_id="repo",
            operation_id="repo.write_text_file",
            plan_sha256=A,
            descriptor_sha256=B,
            custody_ref="custody://x",
            admitted=True,
            reason="invalid",
            readback_verified=True,
            execution_enabled=True,
        )
