"""Transport adapter boundary for ACP authority synchronization."""

from typing import Dict, Protocol

from .authority import AuthorityValidationError
from .authority_sync import (
    AuthoritySyncReconciler,
    decode_sync_message,
    encode_sync_acknowledgement,
)


class AuthoritySyncTransport(Protocol):
    def exchange(self, peer_id: str, payload: bytes) -> bytes:
        """Deliver one canonical ACP sync payload and return canonical acknowledgement bytes."""
        ...


class AuthoritySyncEndpoint:
    """Adapter-facing endpoint; transport supplies bytes, ACP owns decoding/reconciliation."""

    def __init__(self, reconciler: AuthoritySyncReconciler) -> None:
        if not isinstance(reconciler, AuthoritySyncReconciler):
            raise AuthorityValidationError("reconciler must be AuthoritySyncReconciler")
        self.reconciler = reconciler

    def receive(self, payload: bytes) -> bytes:
        message = decode_sync_message(payload)
        acknowledgement = self.reconciler.apply(message)
        return encode_sync_acknowledgement(acknowledgement)


class LoopbackAuthoritySyncTransport:
    """Deterministic in-process adapter used only for transport-boundary conformance tests."""

    def __init__(self) -> None:
        self._peers: Dict[str, AuthoritySyncEndpoint] = {}

    def register(self, peer_id: str, endpoint: AuthoritySyncEndpoint) -> None:
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise AuthorityValidationError("peer_id must not be blank")
        if not isinstance(endpoint, AuthoritySyncEndpoint):
            raise AuthorityValidationError("endpoint must be AuthoritySyncEndpoint")
        key = peer_id.strip()
        if key in self._peers:
            raise AuthorityValidationError("peer already registered")
        self._peers[key] = endpoint

    def exchange(self, peer_id: str, payload: bytes) -> bytes:
        endpoint = self._peers.get(peer_id)
        if endpoint is None:
            raise AuthorityValidationError("unknown sync peer")
        if not isinstance(payload, bytes):
            raise AuthorityValidationError("payload must be bytes")
        return endpoint.receive(payload)
