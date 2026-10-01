from __future__ import annotations

import pytest

from agent_control_plane.remote_mutation_postcondition import (
    MutationPostconditionRecord,
)
from agent_control_plane.remote_mutation_recovery_journal import (
    MutationJournalEvent,
    MutationJournalState,
    MutationRecoveryAssessment,
    MutationRecoveryDisposition,
    MutationRecoveryJournalRecord,
)
from agent_control_plane.remote_mutation_result_binding import (
    MutationExternalOutcome,
    MutationExternalResultReceipt,
    MutationResultBindingError,
    MutationResultBindingRecord,
    bind_mutation_execution_result,
    mutation_postcondition_sha256,
    mutation_result_receipt_sha256,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def verified_postcondition() -> MutationPostconditionRecord:
    return MutationPostconditionRecord(
        request_id="req-result",
        resource_id="repo:acp",
        operation_id="repo.write_text_file",
        plan_sha256=A,
        requested_path="docs/example.md",
        repository_root="C:/repo",
        resolved_path="C:/repo/docs/example.md",
        rollback_descriptor_sha256=B,
        rollback_custody_ref="custody://result/1",
        target_exists=True,
        observed_content_sha256=C,
        path_revalidated=True,
        postcondition_verified=True,
        reason="verified",
    )


def journal_record(
    state: MutationJournalState = MutationJournalState.POSTCONDITION_VERIFIED,
) -> MutationRecoveryJournalRecord:
    events = [
        MutationJournalEvent(
            journal_id="journal-result",
            event_index=0,
            state=MutationJournalState.PREPARED,
        )
    ]
    if state is not MutationJournalState.PREPARED:
        events.append(
            MutationJournalEvent(
                journal_id="journal-result",
                event_index=1,
                state=MutationJournalState.EFFECT_INTENT_RECORDED,
            )
        )
    if state in {
        MutationJournalState.POSTCONDITION_VERIFIED,
        MutationJournalState.CLOSED_VERIFIED,
    }:
        events.append(
            MutationJournalEvent(
                journal_id="journal-result",
                event_index=2,
                state=MutationJournalState.POSTCONDITION_VERIFIED,
            )
        )
    if state is MutationJournalState.CLOSED_VERIFIED:
        events.append(
            MutationJournalEvent(
                journal_id="journal-result",
                event_index=3,
                state=MutationJournalState.CLOSED_VERIFIED,
            )
        )
    return MutationRecoveryJournalRecord(
        journal_id="journal-result",
        request_id="req-result",
        resource_id="repo:acp",
        operation_id="repo.write_text_file",
        plan_sha256=A,
        requested_path="docs/example.md",
        rollback_descriptor_sha256=B,
        rollback_custody_ref="custody://result/1",
        events=tuple(events),
    )


def assessment_for(
    state: MutationJournalState,
) -> MutationRecoveryAssessment:
    if state is MutationJournalState.EFFECT_INTENT_RECORDED:
        disposition = MutationRecoveryDisposition.HOLD_UNKNOWN_EFFECT
        hold = True
    elif state is MutationJournalState.CLOSED_VERIFIED:
        disposition = MutationRecoveryDisposition.CLEAN_VERIFIED
        hold = False
    else:
        disposition = MutationRecoveryDisposition.VERIFIED_EFFECT
        hold = False
    return MutationRecoveryAssessment(
        journal_id="journal-result",
        current_state=state,
        disposition=disposition,
        effect_may_exist=True,
        recovery_hold=hold,
    )


def receipt(
    *,
    outcome: MutationExternalOutcome = MutationExternalOutcome.SUCCEEDED,
    postcondition_sha256: str | None = None,
) -> MutationExternalResultReceipt:
    return MutationExternalResultReceipt(
        execution_id="external-execution-1",
        executor_ref="executor://untrusted/test",
        request_id="req-result",
        resource_id="repo:acp",
        operation_id="repo.write_text_file",
        plan_sha256=A,
        journal_id="journal-result",
        rollback_descriptor_sha256=B,
        rollback_custody_ref="custody://result/1",
        outcome=outcome,
        result_sha256=D,
        postcondition_sha256=postcondition_sha256,
    )


def test_succeeded_receipt_requires_exact_verified_postcondition():
    post = verified_postcondition()
    journal = journal_record()
    assessment = assessment_for(journal.current_state)
    external = receipt(
        postcondition_sha256=mutation_postcondition_sha256(post),
    )

    bound = bind_mutation_execution_result(
        journal,
        assessment,
        external,
        postcondition=post,
    )

    assert bound.receipt_bound is True
    assert bound.postcondition_correlated is True
    assert bound.success_established is True
    assert bound.recovery_hold is False
    assert bound.executor_authenticated is False
    assert bound.execution_authorized is False
    assert bound.acp_mutation_executed is False


@pytest.mark.parametrize(
    "outcome",
    [MutationExternalOutcome.FAILED, MutationExternalOutcome.UNKNOWN],
)
def test_non_success_receipt_never_establishes_success(outcome):
    post = verified_postcondition()
    journal = journal_record()
    bound = bind_mutation_execution_result(
        journal,
        assessment_for(journal.current_state),
        receipt(
            outcome=outcome,
            postcondition_sha256=mutation_postcondition_sha256(post),
        ),
        postcondition=post,
    )

    assert bound.receipt_bound is True
    assert bound.postcondition_correlated is True
    assert bound.success_established is False


def test_unknown_effect_hold_cannot_become_success():
    journal = journal_record(MutationJournalState.EFFECT_INTENT_RECORDED)
    bound = bind_mutation_execution_result(
        journal,
        assessment_for(journal.current_state),
        receipt(outcome=MutationExternalOutcome.SUCCEEDED),
    )

    assert bound.receipt_bound is True
    assert bound.success_established is False
    assert bound.recovery_hold is True


def test_wrong_postcondition_digest_blocks_success_without_relabeling_receipt():
    post = verified_postcondition()
    journal = journal_record()
    bound = bind_mutation_execution_result(
        journal,
        assessment_for(journal.current_state),
        receipt(postcondition_sha256="e" * 64),
        postcondition=post,
    )

    assert bound.receipt_bound is True
    assert bound.postcondition_correlated is False
    assert bound.success_established is False


def test_receipt_identity_substitution_fails_closed():
    journal = journal_record()
    post = verified_postcondition()
    bad = MutationExternalResultReceipt(
        **{
            **receipt(
                postcondition_sha256=mutation_postcondition_sha256(post)
            ).__dict__,
            "plan_sha256": "f" * 64,
        }
    )

    with pytest.raises(MutationResultBindingError, match="journal identity"):
        bind_mutation_execution_result(
            journal,
            assessment_for(journal.current_state),
            bad,
            postcondition=post,
        )


def test_mismatched_recovery_assessment_fails_closed():
    journal = journal_record()
    post = verified_postcondition()
    mismatched = MutationRecoveryAssessment(
        journal_id=journal.journal_id,
        current_state=MutationJournalState.EFFECT_INTENT_RECORDED,
        disposition=MutationRecoveryDisposition.HOLD_UNKNOWN_EFFECT,
        effect_may_exist=True,
        recovery_hold=True,
    )

    with pytest.raises(MutationResultBindingError, match="journal state"):
        bind_mutation_execution_result(
            journal,
            mismatched,
            receipt(
                postcondition_sha256=mutation_postcondition_sha256(post),
            ),
            postcondition=post,
        )


def test_receipt_cannot_reference_missing_postcondition():
    journal = journal_record()
    with pytest.raises(MutationResultBindingError, match="none was supplied"):
        bind_mutation_execution_result(
            journal,
            assessment_for(journal.current_state),
            receipt(postcondition_sha256="e" * 64),
        )


def test_postcondition_identity_substitution_fails_closed():
    journal = journal_record()
    post = verified_postcondition()
    bad_post = MutationPostconditionRecord(
        **{
            **post.__dict__,
            "rollback_custody_ref": "custody://other",
        }
    )

    with pytest.raises(MutationResultBindingError, match="postcondition"):
        bind_mutation_execution_result(
            journal,
            assessment_for(journal.current_state),
            receipt(
                postcondition_sha256=mutation_postcondition_sha256(bad_post),
            ),
            postcondition=bad_post,
        )


def test_receipt_content_identity_is_deterministic():
    post = verified_postcondition()
    external = receipt(
        postcondition_sha256=mutation_postcondition_sha256(post),
    )

    assert mutation_result_receipt_sha256(external) == (
        mutation_result_receipt_sha256(external)
    )


def test_binding_record_cannot_promote_authentication_or_authority():
    with pytest.raises(MutationResultBindingError, match="cannot establish"):
        MutationResultBindingRecord(
            execution_id="external-execution-1",
            executor_ref="executor://untrusted/test",
            request_id="req-result",
            resource_id="repo:acp",
            operation_id="repo.write_text_file",
            plan_sha256=A,
            journal_id="journal-result",
            receipt_sha256=D,
            outcome=MutationExternalOutcome.SUCCEEDED,
            receipt_bound=True,
            success_established=True,
            postcondition_correlated=True,
            recovery_hold=False,
            executor_authenticated=True,
        )
