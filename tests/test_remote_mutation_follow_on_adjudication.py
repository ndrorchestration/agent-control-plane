from agent_control_plane.remote_mutation_admission import RemoteMutationAdmissionRecord
from agent_control_plane.remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorization,
)
from agent_control_plane.remote_mutation_execution_closure import (
    MutationExecutionClosureRecord,
)
from agent_control_plane.remote_mutation_follow_on_adjudication import (
    MutationFollowOnAdjudicationError,
    bind_fresh_follow_on_adjudication,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


def prior_closure(**changes):
    values = dict(
        authorization_id="authz-prior",
        authorization_sha256=A,
        evidence_sha256=B,
        executor_id="executor:test",
        execution_id="exec-prior",
        transaction_id="tx-prior",
        request_id="req-prior",
        resource_id="repo:test",
        operation_id="repo.write_text_file",
        plan_sha256=C,
        closed=True,
        reason="closed",
    )
    values.update(changes)
    return MutationExecutionClosureRecord(**values)


def admission(**changes):
    values = dict(
        admitted=True,
        reason="fresh authority bindings satisfied",
        request_id="req-fresh",
        authority_id="authority-fresh",
        decision_id="decision-fresh",
        policy_id="policy-fresh",
        principal_checked=True,
        capability_checked=True,
        resource_checked=True,
        operation_checked=True,
        lease_checked=True,
        revocation_checked=True,
        delegation_checked=False,
    )
    values.update(changes)
    return RemoteMutationAdmissionRecord(**values)


def authorization(**changes):
    values = dict(
        authorization_id="authz-fresh",
        executor_id="executor:test",
        transaction_id="tx-fresh",
        request_id="req-fresh",
        authority_id="authority-fresh",
        resource_id="repo:test",
        operation_id="repo.write_text_file",
        plan_sha256=A,
        rollback_descriptor_sha256=B,
        custody_ref="custody://fresh",
        issued_at="2026-10-03T12:00:00Z",
        expires_at="2026-10-03T12:05:00Z",
    )
    values.update(changes)
    return RemoteMutationExecutionAuthorization(**values)


def test_binds_closed_prior_evidence_to_fresh_admission_and_authorization():
    record = bind_fresh_follow_on_adjudication(
        prior_closure(),
        admission(),
        authorization(),
    )

    assert record.fresh_adjudication_established is True
    assert record.authority_effect == "NONE"
    assert record.prior_evidence_sha256 == B
    assert record.fresh_authorization_id == "authz-fresh"


def test_reusing_prior_authorization_fails_closed():
    try:
        bind_fresh_follow_on_adjudication(
            prior_closure(),
            admission(),
            authorization(authorization_id="authz-prior"),
        )
    except MutationFollowOnAdjudicationError as exc:
        assert "distinct" in str(exc)
    else:
        raise AssertionError("prior authorization reuse must fail")


def test_reusing_prior_request_fails_closed():
    try:
        bind_fresh_follow_on_adjudication(
            prior_closure(),
            admission(request_id="req-prior"),
            authorization(request_id="req-prior"),
        )
    except MutationFollowOnAdjudicationError as exc:
        assert "request must be distinct" in str(exc)
    else:
        raise AssertionError("prior request reuse must fail")


def test_unadmitted_follow_on_fails_closed():
    try:
        bind_fresh_follow_on_adjudication(
            prior_closure(),
            admission(admitted=False),
            authorization(),
        )
    except MutationFollowOnAdjudicationError as exc:
        assert "not admitted" in str(exc)
    else:
        raise AssertionError("unadmitted follow-on must fail")


def test_admission_identity_must_match_fresh_authorization():
    try:
        bind_fresh_follow_on_adjudication(
            prior_closure(),
            admission(authority_id="authority-other"),
            authorization(),
        )
    except MutationFollowOnAdjudicationError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("mismatched fresh identities must fail")


def test_consumed_follow_on_authorization_fails_closed():
    try:
        bind_fresh_follow_on_adjudication(
            prior_closure(),
            admission(),
            authorization(consumed_at="2026-10-03T12:01:00Z"),
        )
    except MutationFollowOnAdjudicationError as exc:
        assert "already consumed" in str(exc)
    else:
        raise AssertionError("consumed follow-on authorization must fail")
