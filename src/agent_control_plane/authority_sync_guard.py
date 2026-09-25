"""Fail-closed synchronization-progress guard for authority policy evaluation."""

from dataclasses import dataclass
from typing import Optional

from .authority import AuthorityEnvelope, AuthorityValidationError
from .authority_state import AuthorityStateRequirement, AuthorityStateStatus
from .authority_sync import AuthoritySyncReconciler


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


@dataclass(frozen=True)
class AuthoritySyncProgressGuard:
    """Require a known sync-sequence floor before authority may be considered fresh.

    The caller supplies the sender stream and minimum sequence that must have
    been reconciled locally. This is intentionally an external safety bound:
    ACP does not infer a globally latest sequence or consensus state.
    """

    reconciler: AuthoritySyncReconciler
    sender_id: str
    min_sequence: int
    state_requirement: Optional[AuthorityStateRequirement] = None

    def __post_init__(self) -> None:
        if not isinstance(self.reconciler, AuthoritySyncReconciler):
            raise AuthorityValidationError(
                "reconciler must be AuthoritySyncReconciler"
            )
        object.__setattr__(self, "sender_id", _required(self.sender_id, "sender_id"))
        if (
            isinstance(self.min_sequence, bool)
            or not isinstance(self.min_sequence, int)
            or self.min_sequence < 0
        ):
            raise AuthorityValidationError("min_sequence must be an integer >= 0")
        if self.state_requirement is not None and not isinstance(
            self.state_requirement,
            AuthorityStateRequirement,
        ):
            raise AuthorityValidationError(
                "state_requirement must be AuthorityStateRequirement or None"
            )

    def __call__(self, authority: AuthorityEnvelope, observed_at: str) -> str | None:
        if not isinstance(authority, AuthorityEnvelope):
            raise AuthorityValidationError("authority must be AuthorityEnvelope")

        manifest = self.reconciler.manifest()
        sender_sequences = manifest.get("sender_sequences")
        if not isinstance(sender_sequences, dict):
            raise AuthorityValidationError("reconciler sender sequence state unavailable")

        observed_sequence = sender_sequences.get(self.sender_id)
        if (
            not isinstance(observed_sequence, int)
            or observed_sequence < self.min_sequence
        ):
            return "sync_sequence"

        if self.state_requirement is None:
            return None

        state = self.reconciler.state_cache.evaluate(
            authority.authority_id,
            observed_at,
            self.state_requirement,
        )
        if state.status is AuthorityStateStatus.CURRENT:
            return None
        return state.status.value
