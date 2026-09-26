"""Fail-closed recovery admission policy for ACP supervisor startup."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .authority import AuthorityValidationError
from .supervisor_runtime_checkpoint import (
    SupervisorPreviousRunDisposition,
    SupervisorRecoveryAssessment,
)


class SupervisorRecoveryDecision(str, Enum):
    ALLOW = "allow"
    HOLD = "hold"


@dataclass(frozen=True)
class SupervisorRecoveryAdmissionPolicy:
    """Decide whether a new supervisor generation may start workers."""

    allowed_dispositions: tuple[
        SupervisorPreviousRunDisposition, ...
    ] = (
        SupervisorPreviousRunDisposition.FRESH,
        SupervisorPreviousRunDisposition.CLEAN_STOP,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_dispositions, tuple):
            raise AuthorityValidationError(
                "allowed_dispositions must be a tuple"
            )
        if not all(
            isinstance(value, SupervisorPreviousRunDisposition)
            for value in self.allowed_dispositions
        ):
            raise AuthorityValidationError(
                "allowed_dispositions must contain "
                "SupervisorPreviousRunDisposition values"
            )
        if len(set(self.allowed_dispositions)) != len(
            self.allowed_dispositions
        ):
            raise AuthorityValidationError(
                "allowed_dispositions must not contain duplicates"
            )

    def decide(
        self,
        assessment: SupervisorRecoveryAssessment,
    ) -> SupervisorRecoveryDecision:
        if not isinstance(assessment, SupervisorRecoveryAssessment):
            raise AuthorityValidationError(
                "assessment must be SupervisorRecoveryAssessment"
            )
        if assessment.disposition in self.allowed_dispositions:
            return SupervisorRecoveryDecision.ALLOW
        return SupervisorRecoveryDecision.HOLD
