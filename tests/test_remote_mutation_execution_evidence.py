from __future__ import annotations

import pytest

from agent_control_plane.remote_mutation_execution_evidence import (
    MUTATION_EXECUTION_EVIDENCE_SCHEMA_VERSION,
    ExternalMutationExecutionEvidence,
    MutationExecutionEvidenceError,
    MutationExecutionEvidenceReceipt,
    bind_mutation_execution_evidence,
)
from agent_control_plane.remote_mutation_journal import (
    MutationJournalEvent,
    MutationJournalRecord,
    MutationJournalState,
)
from agent_control_plane.remote_mutation_postcondition import MutationPostconditionRecord
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_transaction import MutationPlan

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64


def plan():
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=B,
        prior_content_size=6,
    )
    return MutationPlan(
        request_id="req-evidence-1",
        authority_id="auth-evidence-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={"path": "docs/example.md", "content_sha256": C},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )


def journal_for(p: MutationPlan, *, effect_sha=D, post_sha=E, current=MutationJournalState.POSTCONDITION_VERIFIED):
    events = [
        MutationJournalEvent(
            transaction_id="tx-evidence-1", event_index=0,
            state=MutationJournalState.PREPARED, occurred_at="2026-09-27T09:00:00Z",
        ),
        MutationJournalEvent(
            transaction_id="tx-evidence-1", event_index=1,
            state=MutationJournalState.EXECUTION_INTENT_RECORDED, occurred_at="2026-09-27T09:00:01Z",
        ),
        MutationJournalEvent(
            transaction_id="tx-evidence-1", event_index=2,
            state=MutationJournalState.EXTERNAL_EFFECT_REPORTED, occurred_at="2026-09-27T09:00:02Z",
            evidence_sha256=effect_sha,
        ),
    ]
    if current is MutationJournalState.POSTCONDITION_VERIFIED:
        events.append(
            MutationJournalEvent(
                transaction_id="tx-evidence-1", event_index=3,
                state=MutationJournalState.POSTCONDITION_VERIFIED, occurred_at="2026-09-27T09:00:03Z",
                evidence_sha256=post_sha,
            )
        )
    return MutationJournalRecord(
        transaction_id="tx-evidence-1",
        request_id=p.request_id,
        resource_id=p.resource_id,
        operation_id=p.operation_id,
        plan_sha256=p.plan_sha256,
        rollback_descriptor_sha256=p.rollback_sha256,
        custody_ref="custody://operator-local/evidence-1",
        created_at="2026-09-27T09:00:00Z",
        events=tuple(events),
    )


def postcondition_for(
    p: MutationPlan,
    *,
    verified=True,
    rollback_descriptor_sha256=None,
    rollback_custody_ref="custody://operator-local/evidence-1",
):
    return MutationPostconditionRecord(
        request_id=p.request_id,
        resource_id=p.resource_id,
        operation_id=p.operation_id,
        plan_sha256=p.plan_sha256,
        requested_path=p.parameters["path"],
        repository_root="C:/repo",
        resolved_path="C:/repo/docs/example.md",
        rollback_descriptor_sha256=rollback_descriptor_sha256 or p.rollback_sha256,
        rollback_custody_ref=rollback_custody_ref,
        target_exists=True,
        observed_content_sha256=p.parameters["content_sha256"],
        path_revalidated=True,
        postcondition_verified=verified,
        reason="verified" if verified else "blocked",
    )


def evidence_for(p: MutationPlan, *, effect_sha=D, post_sha=E, result_sha=A):
    return ExternalMutationExecutionEvidence(
        executor_id="external-executor:test",
        execution_id="exec-1",
        transaction_id="tx-evidence-1",
        request_id=p.request_id,
        resource_id=p.resource_id,
        operation_id=p.operation_id,
        plan_sha256=p.plan_sha256,
        result_sha256=result_sha,
        external_effect_sha256=effect_sha,
        postcondition_evidence_sha256=post_sha,
    )


def test_exact_execution_evidence_binds_without_authorizing_execution():
    p = plan()
    receipt = bind_mutation_execution_evidence(
        p, journal_for(p), postcondition_for(p), evidence_for(p)
    )
    assert receipt.schema_version == MUTATION_EXECUTION_EVIDENCE_SCHEMA_VERSION
    assert receipt.evidence_bound is True
    assert receipt.execution_authorized is False
    assert receipt.acp_mutation_executed is False
    assert receipt.plan_sha256 == p.plan_sha256


def test_evidence_content_identity_is_deterministic():
    p = plan()
    first = evidence_for(p)
    second = evidence_for(p)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.evidence_sha256 == second.evidence_sha256


def test_external_effect_hash_mismatch_blocks():
    p = plan()
    receipt = bind_mutation_execution_evidence(
        p, journal_for(p), postcondition_for(p), evidence_for(p, effect_sha=C)
    )
    assert receipt.evidence_bound is False
    assert "external_effect_sha256" in receipt.reason


def test_postcondition_evidence_hash_mismatch_blocks():
    p = plan()
    receipt = bind_mutation_execution_evidence(
        p, journal_for(p), postcondition_for(p), evidence_for(p, post_sha=D)
    )
    assert receipt.evidence_bound is False
    assert "postcondition_evidence_sha256" in receipt.reason


def test_unverified_postcondition_blocks_even_with_matching_journal():
    p = plan()
    receipt = bind_mutation_execution_evidence(
        p, journal_for(p), postcondition_for(p, verified=False), evidence_for(p)
    )
    assert receipt.evidence_bound is False
    assert "postcondition" in receipt.reason


def test_postcondition_rollback_descriptor_mismatch_blocks():
    p = plan()
    receipt = bind_mutation_execution_evidence(
        p,
        journal_for(p),
        postcondition_for(p, rollback_descriptor_sha256=B),
        evidence_for(p),
    )
    assert receipt.evidence_bound is False
    assert "postcondition" in receipt.reason


def test_postcondition_custody_reference_mismatch_blocks():
    p = plan()
    receipt = bind_mutation_execution_evidence(
        p,
        journal_for(p),
        postcondition_for(p, rollback_custody_ref="custody://operator-local/other"),
        evidence_for(p),
    )
    assert receipt.evidence_bound is False
    assert "postcondition" in receipt.reason


def test_journal_must_be_terminal_verified_postcondition():
    p = plan()
    j = journal_for(p, current=MutationJournalState.EXTERNAL_EFFECT_REPORTED)
    receipt = bind_mutation_execution_evidence(
        p, j, postcondition_for(p), evidence_for(p)
    )
    assert receipt.evidence_bound is False
    assert "journal.current_state" in receipt.reason
    assert "journal.postcondition_event" in receipt.reason


def test_plan_identity_drift_blocks():
    p = plan()
    other = MutationPlan(
        request_id="other-request",
        authority_id=p.authority_id,
        resource_id=p.resource_id,
        resource_type=p.resource_type,
        operation_id=p.operation_id,
        parameters=dict(p.parameters),
        precondition_sha256=p.precondition_sha256,
        rollback_sha256=p.rollback_sha256,
    )
    receipt = bind_mutation_execution_evidence(
        other, journal_for(p), postcondition_for(p), evidence_for(p)
    )
    assert receipt.evidence_bound is False
    assert "journal.plan_identity" in receipt.reason
    assert "postcondition" in receipt.reason
    assert "evidence.plan_identity" in receipt.reason


def test_transaction_id_mismatch_blocks():
    p = plan()
    e = ExternalMutationExecutionEvidence(
        executor_id="external-executor:test", execution_id="exec-1",
        transaction_id="tx-other", request_id=p.request_id, resource_id=p.resource_id,
        operation_id=p.operation_id, plan_sha256=p.plan_sha256, result_sha256=A,
        external_effect_sha256=D, postcondition_evidence_sha256=E,
    )
    receipt = bind_mutation_execution_evidence(p, journal_for(p), postcondition_for(p), e)
    assert receipt.evidence_bound is False
    assert "evidence.plan_identity" in receipt.reason


def test_receipt_cannot_authorize_execution():
    with pytest.raises(MutationExecutionEvidenceError, match="cannot authorize"):
        MutationExecutionEvidenceReceipt(
            transaction_id="tx", execution_id="exec", executor_id="external:test",
            request_id="req", resource_id="repo", operation_id="repo.write_text_file",
            plan_sha256=A, result_sha256=B, external_effect_sha256=C,
            postcondition_evidence_sha256=D, evidence_sha256=E, evidence_bound=True,
            reason="invalid", execution_authorized=True,
        )


@pytest.mark.parametrize("field", ["result_sha256", "external_effect_sha256", "postcondition_evidence_sha256"])
def test_evidence_rejects_malformed_hashes(field):
    p = plan()
    values = {
        "executor_id": "external:test", "execution_id": "exec-1",
        "transaction_id": "tx-evidence-1", "request_id": p.request_id,
        "resource_id": p.resource_id, "operation_id": p.operation_id,
        "plan_sha256": p.plan_sha256, "result_sha256": A,
        "external_effect_sha256": D, "postcondition_evidence_sha256": E,
    }
    values[field] = "bad"
    with pytest.raises(MutationExecutionEvidenceError, match="sha256"):
        ExternalMutationExecutionEvidence(**values)