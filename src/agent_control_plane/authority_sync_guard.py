"""Fail-closed synchronization-progress guard for authority policy evaluation."""

from dataclasses import dataclass
from typing import Optional

from .authority import AuthorityEnvelope, AuthorityValidationError
from .authority_state import AuthorityStateRequirement, AuthorityStateStatus
from .authority_sync import AuthoritySyncReconciler
from .authority_sync_watermark import AuthoritySyncWatermarkRegistry


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


@dataclass(frozen=True)
class AuthoritySyncProgressGuard:
    """Require a known sync-sequence floor before authority may be considered fresh.

    The caller supplies the sender stream and either a static minimum sequence,
    a trusted watermark registry, or both. Dynamic watermarks can only raise the
    local floor; ACP does not infer a globally latest sequence or consensus state.
    """

    reconciler: AuthoritySyncReconciler
    sender_id: str
    min_sequence: Optional[int] = None
    state_requirement: Optional[AuthorityStateRequirement] = None
    watermark_registry: Optional[AuthoritySyncWatermarkRegistry] = None

    def __post_init__(self) -> None:
        if not isinstance(self.reconciler, AuthoritySyncReconciler):
            raise AuthorityValidationError(
                "reconciler must be AuthoritySyncReconciler"
            )
        object.__setattr__(self, "sender_id", _required(self.sender_id, "sender_id"))
        if self.min_sequence is not None and (
            isinstance(self.min_sequence, bool)
            or not isinstance(self.min_sequence, int)
            or self.min_sequence < 0
        ):
            raise AuthorityValidationError("min_sequence must be an integer >= 0 or None")
        if self.watermark_registry is not None and not isinstance(
            self.watermark_registry,
            AuthoritySyncWatermarkRegistry,
        ):
            raise AuthorityValidationError(
                "watermark_registry must be AuthoritySyncWatermarkRegistry or None"
            )
        if self.min_sequence is None and self.watermark_registry is None:
            raise AuthorityValidationError(
                "min_sequence or watermark_registry must be configured"
            )
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

        required_sequences = []
        if self.min_sequence is not None:
            required_sequences.append(self.min_sequence)
        if self.watermark_registry is not None:
            dynamic_floor = self.watermark_registry.required_sequence(self.sender_id)
            if dynamic_floor is None:
                return "sync_watermark_missing"
            required_sequences.append(dynamic_floor)

        required_sequence = max(required_sequences)
        observed_sequence = sender_sequences.get(self.sender_id)
        if (
            not isinstance(observed_sequence, int)
            or observed_sequence < required_sequence
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
