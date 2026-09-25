"""Transport boundary for ACP authority synchronization watermarks."""

from typing import Dict, Protocol

from .authority import AuthorityValidationError
from .authority_sync_watermark import (
    AuthoritySyncWatermarkAcknowledgement,
    AuthoritySyncWatermarkRegistry,
    decode_authority_sync_watermark,
    encode_authority_sync_watermark_acknowledgement,
)


class AuthoritySyncWatermarkTransport(Protocol):
    def exchange(self, peer_id: str, payload: bytes) -> bytes:
        """Deliver one canonical watermark and return canonical acknowledgement bytes."""
        ...


class AuthoritySyncWatermarkEndpoint:
    def __init__(self, *, receiver_id: str, registry: AuthoritySyncWatermarkRegistry) -> None:
        if not isinstance(receiver_id, str) or not receiver_id.strip():
            raise AuthorityValidationError("receiver_id must not be blank")
        if not isinstance(registry, AuthoritySyncWatermarkRegistry):
            raise AuthorityValidationError("registry must be AuthoritySyncWatermarkRegistry")
        self.receiver_id = receiver_id.strip()
        self.registry = registry

    def receive(self, payload: bytes) -> bytes:
        if not isinstance(payload, bytes):
            raise AuthorityValidationError("payload must be bytes")
        watermark = decode_authority_sync_watermark(payload)
        disposition = self.registry.apply(watermark)
        acknowledgement = AuthoritySyncWatermarkAcknowledgement(
            watermark_id=watermark.watermark_id,
            issuer_id=watermark.issuer_id,
            receiver_id=self.receiver_id,
            target_sender_id=watermark.target_sender_id,
            min_sequence=watermark.min_sequence,
            disposition=disposition,
        )
        return encode_authority_sync_watermark_acknowledgement(acknowledgement)


class LoopbackAuthoritySyncWatermarkTransport:
    """Deterministic in-process conformance adapter for watermark exchange."""

    def __init__(self) -> None:
        self._peers: Dict[str, AuthoritySyncWatermarkEndpoint] = {}

    def register(self, peer_id: str, endpoint: AuthoritySyncWatermarkEndpoint) -> None:
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise AuthorityValidationError("peer_id must not be blank")
        if not isinstance(endpoint, AuthoritySyncWatermarkEndpoint):
            raise AuthorityValidationError("endpoint must be AuthoritySyncWatermarkEndpoint")
        key = peer_id.strip()
        if key in self._peers:
            raise AuthorityValidationError("watermark peer already registered")
        self._peers[key] = endpoint

    def exchange(self, peer_id: str, payload: bytes) -> bytes:
        if not isinstance(peer_id, str) or not peer_id.strip():
            raise AuthorityValidationError("peer_id must not be blank")
        if not isinstance(payload, bytes):
            raise AuthorityValidationError("payload must be bytes")
        endpoint = self._peers.get(peer_id.strip())
        if endpoint is None:
            raise AuthorityValidationError("unknown watermark peer")
        return endpoint.receive(payload)
