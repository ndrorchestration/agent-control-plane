"""Transport-neutral authority synchronization candidate for ACP."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, Tuple, Union

from .authority import AuthorityValidationError
from .authority_state import AuthorityStateSnapshot, InMemoryAuthorityStateCache
from .revocation import InMemoryRevocationRegistry, RevocationRecord


AUTHORITY_SYNC_SCHEMA_VERSION = "agent-control-plane.authority-sync.v0-candidate"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


class SyncMessageKind(str, Enum):
    SNAPSHOT = "snapshot"
    REVOCATION = "revocation"


class SyncDisposition(str, Enum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SnapshotSyncMessage:
    message_id: str
    sender_id: str
    sequence: int
    snapshot: AuthorityStateSnapshot
    schema_version: str = AUTHORITY_SYNC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _required(self.message_id, "message_id"))
        object.__setattr__(self, "sender_id", _required(self.sender_id, "sender_id"))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise AuthorityValidationError("sequence must be an integer >= 0")
        if not isinstance(self.snapshot, AuthorityStateSnapshot):
            raise AuthorityValidationError("snapshot must be AuthorityStateSnapshot")
        if self.schema_version != AUTHORITY_SYNC_SCHEMA_VERSION:
            raise AuthorityValidationError(f"unsupported schema_version: {self.schema_version}")

    @property
    def kind(self) -> SyncMessageKind:
        return SyncMessageKind.SNAPSHOT

    def to_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "snapshot": self.snapshot.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RevocationSyncMessage:
    message_id: str
    sender_id: str
    sequence: int
    revocation: RevocationRecord
    schema_version: str = AUTHORITY_SYNC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_id", _required(self.message_id, "message_id"))
        object.__setattr__(self, "sender_id", _required(self.sender_id, "sender_id"))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise AuthorityValidationError("sequence must be an integer >= 0")
        if not isinstance(self.revocation, RevocationRecord):
            raise AuthorityValidationError("revocation must be RevocationRecord")
        if self.schema_version != AUTHORITY_SYNC_SCHEMA_VERSION:
            raise AuthorityValidationError(f"unsupported schema_version: {self.schema_version}")

    @property
    def kind(self) -> SyncMessageKind:
        return SyncMessageKind.REVOCATION

    def to_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "revocation": self.revocation.to_dict(),
            "schema_version": self.schema_version,
        }


SyncMessage = Union[SnapshotSyncMessage, RevocationSyncMessage]


@dataclass(frozen=True)
class SyncAcknowledgement:
    message_id: str
    sender_id: str
    receiver_id: str
    disposition: SyncDisposition
    reason_code: str
    applied_sequence: int | None
    authority_id: str | None
    schema_version: str = AUTHORITY_SYNC_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["disposition"] = self.disposition.value
        return data


class AuthoritySyncReconciler:
    """Apply transport-neutral authority messages with replay/conflict fail-closure."""

    def __init__(
        self,
        *,
        receiver_id: str,
        state_cache: InMemoryAuthorityStateCache,
        revocations: InMemoryRevocationRegistry,
    ) -> None:
        self.receiver_id = _required(receiver_id, "receiver_id")
        if not isinstance(state_cache, InMemoryAuthorityStateCache):
            raise AuthorityValidationError("state_cache must be InMemoryAuthorityStateCache")
        if not isinstance(revocations, InMemoryRevocationRegistry):
            raise AuthorityValidationError("revocations must be InMemoryRevocationRegistry")
        self.state_cache = state_cache
        self.revocations = revocations
        self._message_fingerprints: Dict[str, Tuple[str, int, str]] = {}
        self._sender_sequences: Dict[str, int] = {}

    def _fingerprint(self, message: SyncMessage) -> Tuple[str, int, str]:
        return (message.sender_id, message.sequence, repr(message.to_dict()))

    def apply(self, message: SyncMessage) -> SyncAcknowledgement:
        if not isinstance(message, (SnapshotSyncMessage, RevocationSyncMessage)):
            raise AuthorityValidationError("message must be a supported sync message")

        fingerprint = self._fingerprint(message)
        prior = self._message_fingerprints.get(message.message_id)
        if prior is not None:
            if prior != fingerprint:
                return self._ack(message, SyncDisposition.REJECTED, "message_id_conflict", None)
            return self._ack(message, SyncDisposition.DUPLICATE, "duplicate_message", message.sequence)

        last_sequence = self._sender_sequences.get(message.sender_id)
        if last_sequence is not None and message.sequence <= last_sequence:
            return self._ack(message, SyncDisposition.REJECTED, "replay_or_sequence_regression", last_sequence)

        try:
            if isinstance(message, SnapshotSyncMessage):
                self.state_cache.update(message.snapshot)
                authority_id = message.snapshot.authority_id
            else:
                self.revocations.revoke(message.revocation)
                authority_id = message.revocation.authority_id
        except AuthorityValidationError as exc:
            return self._ack(message, SyncDisposition.REJECTED, str(exc), last_sequence)

        self._message_fingerprints[message.message_id] = fingerprint
        self._sender_sequences[message.sender_id] = message.sequence
        return SyncAcknowledgement(
            message_id=message.message_id,
            sender_id=message.sender_id,
            receiver_id=self.receiver_id,
            disposition=SyncDisposition.APPLIED,
            reason_code="applied",
            applied_sequence=message.sequence,
            authority_id=authority_id,
        )

    def _ack(
        self,
        message: SyncMessage,
        disposition: SyncDisposition,
        reason_code: str,
        applied_sequence: int | None,
    ) -> SyncAcknowledgement:
        if isinstance(message, SnapshotSyncMessage):
            authority_id = message.snapshot.authority_id
        else:
            authority_id = message.revocation.authority_id
        return SyncAcknowledgement(
            message_id=message.message_id,
            sender_id=message.sender_id,
            receiver_id=self.receiver_id,
            disposition=disposition,
            reason_code=reason_code,
            applied_sequence=applied_sequence,
            authority_id=authority_id,
        )

    def manifest(self) -> dict[str, object]:
        return {
            "schema": AUTHORITY_SYNC_SCHEMA_VERSION,
            "receiver_id": self.receiver_id,
            "sender_sequences": dict(sorted(self._sender_sequences.items())),
            "seen_message_count": len(self._message_fingerprints),
        }
