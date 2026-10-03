"""Bind a prior terminal mutation result to a fresh follow-on adjudication.

This module does not adjudicate by itself and does not authorize execution.
It verifies that a caller-supplied fresh mutation admission and a distinct
current execution authorization are exactly bound after a closed prior effect.
"""

from __future__ import annotations

from dataclasses import dataclass

from .remote_mutation_admission import RemoteMutationAdmissionRecord
from .remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorization,
)
from .remote_mutation_execution_closure import MutationExecutionClosureRecord

MUTATION_FOLLOW_ON_ADJUDICATION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-follow-on-adjudication.v0-candidate"
)


class MutationFollowOnAdjudicationError(ValueError):
    pass


@dataclass(frozen=True)
class MutationFollowOnAdjudicationRecord:
    prior_authorization_id: str
    prior_evidence_sha256: str
    prior_request_id: str
    fresh_request_id: str
    fresh_authority_id: str
    fresh_decision_id: str
    fresh_policy_id: str
    fresh_authorization_id: str
    fresh_adjudication_established: bool
    authority_effect: str = "NONE"
    schema_version: str = MUTATION_FOLLOW_ON_ADJUDICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.fresh_adjudication_established is not True:
            raise MutationFollowOnAdjudicationError(
                "follow-on record must establish fresh adjudication"
            )
        if self.authority_effect != "NONE":
            raise MutationFollowOnAdjudicationError(
                "follow-on adjudication record cannot carry authority"
            )
        if self.prior_authorization_id == self.fresh_authorization_id:
            raise MutationFollowOnAdjudicationError(
                "follow-on authorization must be distinct from prior authorization"
            )
        if self.prior_request_id == self.fresh_request_id:
            raise MutationFollowOnAdjudicationError(
                "follow-on request must be distinct from prior request"
            )


def bind_fresh_follow_on_adjudication(
    prior_closure: MutationExecutionClosureRecord,
    fresh_admission: RemoteMutationAdmissionRecord,
    fresh_authorization: RemoteMutationExecutionAuthorization,
) -> MutationFollowOnAdjudicationRecord:
    """Require fresh admitted authority and a new unconsumed authorization."""
    if not isinstance(prior_closure, MutationExecutionClosureRecord):
        raise TypeError("prior_closure must be MutationExecutionClosureRecord")
    if not isinstance(fresh_admission, RemoteMutationAdmissionRecord):
        raise TypeError("fresh_admission must be RemoteMutationAdmissionRecord")
    if not isinstance(
        fresh_authorization, RemoteMutationExecutionAuthorization
    ):
        raise TypeError(
            "fresh_authorization must be RemoteMutationExecutionAuthorization"
        )

    if prior_closure.closed is not True:
        raise MutationFollowOnAdjudicationError(
            "prior execution must be closed before follow-on adjudication"
        )
    if (
        prior_closure.further_execution_authorized is not False
        or prior_closure.acp_mutation_executed is not False
    ):
        raise MutationFollowOnAdjudicationError(
            "prior closure unexpectedly carries execution authority"
        )
    if fresh_admission.admitted is not True:
        raise MutationFollowOnAdjudicationError(
            "fresh mutation admission is not admitted"
        )
    if fresh_admission.execution_enabled is not False:
        raise MutationFollowOnAdjudicationError(
            "fresh mutation admission unexpectedly enables execution"
        )
    if (
        fresh_admission.authority_id is None
        or fresh_admission.decision_id is None
        or fresh_admission.policy_id is None
    ):
        raise MutationFollowOnAdjudicationError(
            "fresh admission lacks authority/decision/policy identity"
        )
    if fresh_authorization.consumed:
        raise MutationFollowOnAdjudicationError(
            "fresh follow-on authorization is already consumed"
        )
    if fresh_authorization.authorization_id == prior_closure.authorization_id:
        raise MutationFollowOnAdjudicationError(
            "follow-on authorization must be distinct from prior authorization"
        )
    if fresh_authorization.request_id == prior_closure.request_id:
        raise MutationFollowOnAdjudicationError(
            "follow-on request must be distinct from prior request"
        )
    if (
        fresh_admission.request_id != fresh_authorization.request_id
        or fresh_admission.authority_id != fresh_authorization.authority_id
    ):
        raise MutationFollowOnAdjudicationError(
            "fresh admission does not match follow-on authorization"
        )

    return MutationFollowOnAdjudicationRecord(
        prior_authorization_id=prior_closure.authorization_id,
        prior_evidence_sha256=prior_closure.evidence_sha256,
        prior_request_id=prior_closure.request_id,
        fresh_request_id=fresh_authorization.request_id,
        fresh_authority_id=fresh_authorization.authority_id,
        fresh_decision_id=fresh_admission.decision_id,
        fresh_policy_id=fresh_admission.policy_id,
        fresh_authorization_id=fresh_authorization.authorization_id,
        fresh_adjudication_established=True,
    )
