"""Experimental Reticulum adapter for ACP authority synchronization.

This module targets the documented Reticulum Link.request(...) and
Destination.register_request_handler(...) APIs while keeping RNS optional at
import time. Live network behavior requires an actual Reticulum installation
and runtime verification.
"""

from dataclasses import dataclass
import time
from typing import Any, Callable, Mapping, Optional

from .authority import AuthorityValidationError
from .authority_sync import decode_sync_message
from .authority_sync_watermark import decode_authority_sync_watermark
from .authority_sync_watermark_relay import (
    RelayedWatermarkEndpoint,
    decode_relayed_authenticated_watermark,
)
from .authority_sync_watermark_relay_chain import (
    Ed25519RelayChainEndpoint,
    decode_ed25519_relay_chain,
)
from .sync_transport import AuthoritySyncEndpoint
from .watermark_transport import AuthoritySyncWatermarkEndpoint


RETICULUM_SYNC_PATH = "/ndrorchestration/acp/authority-sync/v0"
RETICULUM_WATERMARK_PATH = "/ndrorchestration/acp/authority-sync-watermark/v0"
RETICULUM_WATERMARK_RELAY_PATH = "/ndrorchestration/acp/authority-sync-watermark-relay/v0"
RETICULUM_WATERMARK_RELAY_CHAIN_PATH = "/ndrorchestration/acp/authority-sync-watermark-relay-chain/v0"


class ReticulumAdapterError(RuntimeError):
    """Raised when the Reticulum adapter cannot complete a bounded exchange."""


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


@dataclass
class ReticulumAuthoritySyncTransport:
    """Synchronous ACP transport over already-established Reticulum links.

    ``peer_links`` maps ACP peer IDs to live objects implementing the documented
    RNS.Link.request(...) / RNS.RequestReceipt surface.
    """

    peer_links: Mapping[str, Any]
    peer_destination_hashes: Optional[Mapping[str, bytes]] = None
    request_path: str = RETICULUM_SYNC_PATH
    timeout_seconds: float = 15.0
    max_response_size: int = 65536
    poll_interval_seconds: float = 0.01
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        self.request_path = _required(self.request_path, "request_path")
        self.peer_destination_hashes = dict(self.peer_destination_hashes or {})
        for peer_id, destination_hash in self.peer_destination_hashes.items():
            _required(peer_id, "peer_id")
            if not isinstance(destination_hash, bytes) or not destination_hash:
                raise AuthorityValidationError("peer destination hashes must be non-empty bytes")
        if self.timeout_seconds <= 0:
            raise AuthorityValidationError("timeout_seconds must be > 0")
        if isinstance(self.max_response_size, bool) or not isinstance(self.max_response_size, int) or self.max_response_size <= 0:
            raise AuthorityValidationError("max_response_size must be an integer > 0")
        if self.poll_interval_seconds <= 0:
            raise AuthorityValidationError("poll_interval_seconds must be > 0")

    def exchange(self, peer_id: str, payload: bytes) -> bytes:
        peer = _required(peer_id, "peer_id")
        if not isinstance(payload, bytes):
            raise AuthorityValidationError("payload must be bytes")
        link = self.peer_links.get(peer)
        if link is None:
            raise ReticulumAdapterError("unknown Reticulum peer link")

        expected_destination_hash = self.peer_destination_hashes.get(peer)
        if expected_destination_hash is not None:
            destination = getattr(link, "destination", None)
            if destination is None:
                raise ReticulumAdapterError("Reticulum link destination unavailable")
            actual_destination_hash = getattr(destination, "hash", None)
            if callable(actual_destination_hash):
                actual_destination_hash = actual_destination_hash()
            if not isinstance(actual_destination_hash, bytes) or not actual_destination_hash:
                raise ReticulumAdapterError("Reticulum destination hash unavailable")
            if actual_destination_hash != expected_destination_hash:
                raise ReticulumAdapterError("Reticulum destination does not match ACP peer_id")

        try:
            receipt = link.request(
                self.request_path,
                data=payload,
                timeout=self.timeout_seconds,
                max_response_size=self.max_response_size,
            )
        except Exception as exc:
            raise ReticulumAdapterError("Reticulum request dispatch failed") from exc

        if receipt is False or receipt is None:
            raise ReticulumAdapterError("Reticulum request was not sent")

        deadline = self.monotonic() + self.timeout_seconds
        while True:
            try:
                if receipt.concluded():
                    break
            except Exception as exc:
                raise ReticulumAdapterError("Reticulum request receipt failed") from exc
            if self.monotonic() >= deadline:
                raise ReticulumAdapterError("Reticulum request timed out locally")
            self.sleep(self.poll_interval_seconds)

        try:
            response = receipt.get_response()
        except Exception as exc:
            raise ReticulumAdapterError("Reticulum response retrieval failed") from exc
        if not isinstance(response, bytes):
            raise ReticulumAdapterError("Reticulum request concluded without byte response")
        if len(response) > self.max_response_size:
            raise ReticulumAdapterError("Reticulum response exceeded configured maximum")
        return response


class ReticulumAuthoritySyncServer:
    """Bind an ACP authority-sync endpoint to a Reticulum Destination handler."""

    def __init__(
        self,
        *,
        destination: Any,
        endpoint: AuthoritySyncEndpoint,
        request_path: str = RETICULUM_SYNC_PATH,
        peer_identity_hashes: Optional[Mapping[str, bytes]] = None,
    ) -> None:
        if not isinstance(endpoint, AuthoritySyncEndpoint):
            raise AuthorityValidationError("endpoint must be AuthoritySyncEndpoint")
        self.destination = destination
        self.endpoint = endpoint
        self.request_path = _required(request_path, "request_path")
        self.peer_identity_hashes = dict(peer_identity_hashes or {})
        for sender_id, identity_hash in self.peer_identity_hashes.items():
            _required(sender_id, "sender_id")
            if not isinstance(identity_hash, bytes) or not identity_hash:
                raise AuthorityValidationError("peer identity hashes must be non-empty bytes")
        self._installed = False

    def install(
        self,
        *,
        allow: Any,
        allowed_list: Optional[list[Any]] = None,
        auto_compress: bool | int = True,
    ) -> None:
        if self._installed:
            raise ReticulumAdapterError("Reticulum request handler already installed")
        try:
            self.destination.register_request_handler(
                self.request_path,
                response_generator=self._handle_request,
                allow=allow,
                allowed_list=allowed_list,
                auto_compress=auto_compress,
            )
        except Exception as exc:
            raise ReticulumAdapterError("Reticulum request handler registration failed") from exc
        self._installed = True

    def _handle_request(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        del request_id, link_id, requested_at
        if path != self.request_path:
            raise ReticulumAdapterError("unexpected Reticulum request path")
        if not isinstance(data, bytes):
            raise ReticulumAdapterError("Reticulum request payload must be bytes")
        if self.peer_identity_hashes:
            message = decode_sync_message(data)
            expected_hash = self.peer_identity_hashes.get(message.sender_id)
            if expected_hash is None:
                raise ReticulumAdapterError("unbound ACP sender_id")
            if remote_identity is None:
                raise ReticulumAdapterError("Reticulum remote identity required")
            actual_hash = getattr(remote_identity, "hash", None)
            if callable(actual_hash):
                actual_hash = actual_hash()
            if not isinstance(actual_hash, bytes) or not actual_hash:
                raise ReticulumAdapterError("Reticulum remote identity hash unavailable")
            if actual_hash != expected_hash:
                raise ReticulumAdapterError("Reticulum identity does not match ACP sender_id")
        return self.endpoint.receive(data)



class ReticulumAuthoritySyncWatermarkTransport(ReticulumAuthoritySyncTransport):
    """Carry ACP watermark bytes over already-established Reticulum links."""

    def __init__(
        self,
        peer_links: Mapping[str, Any],
        peer_destination_hashes: Optional[Mapping[str, bytes]] = None,
        **kwargs: Any,
    ) -> None:
        if "request_path" in kwargs:
            raise AuthorityValidationError(
                "watermark transport request_path is fixed"
            )
        super().__init__(
            peer_links=peer_links,
            peer_destination_hashes=peer_destination_hashes,
            request_path=RETICULUM_WATERMARK_PATH,
            **kwargs,
        )


class ReticulumAuthoritySyncWatermarkServer:
    """Bind an ACP watermark endpoint to a Reticulum Destination handler."""

    def __init__(
        self,
        *,
        destination: Any,
        endpoint: AuthoritySyncWatermarkEndpoint,
        peer_identity_hashes: Optional[Mapping[str, bytes]] = None,
    ) -> None:
        if not isinstance(endpoint, AuthoritySyncWatermarkEndpoint):
            raise AuthorityValidationError(
                "endpoint must be AuthoritySyncWatermarkEndpoint"
            )
        self.destination = destination
        self.endpoint = endpoint
        self.request_path = RETICULUM_WATERMARK_PATH
        self.peer_identity_hashes = dict(peer_identity_hashes or {})
        for issuer_id, identity_hash in self.peer_identity_hashes.items():
            _required(issuer_id, "issuer_id")
            if not isinstance(identity_hash, bytes) or not identity_hash:
                raise AuthorityValidationError(
                    "peer identity hashes must be non-empty bytes"
                )
        self._installed = False

    def install(
        self,
        *,
        allow: Any,
        allowed_list: Optional[list[Any]] = None,
        auto_compress: bool | int = True,
    ) -> None:
        if self._installed:
            raise ReticulumAdapterError(
                "Reticulum watermark request handler already installed"
            )
        try:
            self.destination.register_request_handler(
                self.request_path,
                response_generator=self._handle_request,
                allow=allow,
                allowed_list=allowed_list,
                auto_compress=auto_compress,
            )
        except Exception as exc:
            raise ReticulumAdapterError(
                "Reticulum watermark handler registration failed"
            ) from exc
        self._installed = True

    def _handle_request(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        del request_id, link_id, requested_at
        if path != self.request_path:
            raise ReticulumAdapterError(
                "unexpected Reticulum watermark request path"
            )
        if not isinstance(data, bytes):
            raise ReticulumAdapterError(
                "Reticulum watermark payload must be bytes"
            )
        if self.peer_identity_hashes:
            watermark = decode_authority_sync_watermark(data)
            expected_hash = self.peer_identity_hashes.get(watermark.issuer_id)
            if expected_hash is None:
                raise ReticulumAdapterError("unbound ACP watermark issuer_id")
            if remote_identity is None:
                raise ReticulumAdapterError(
                    "Reticulum remote identity required for watermark"
                )
            actual_hash = getattr(remote_identity, "hash", None)
            if callable(actual_hash):
                actual_hash = actual_hash()
            if not isinstance(actual_hash, bytes) or not actual_hash:
                raise ReticulumAdapterError(
                    "Reticulum remote identity hash unavailable"
                )
            if actual_hash != expected_hash:
                raise ReticulumAdapterError(
                    "Reticulum identity does not match ACP watermark issuer_id"
                )
        return self.endpoint.receive(data)



class ReticulumRelayedWatermarkTransport(ReticulumAuthoritySyncTransport):
    """Carry one-hop relayed authenticated watermark bytes over Reticulum."""

    def __init__(
        self,
        peer_links: Mapping[str, Any],
        peer_destination_hashes: Optional[Mapping[str, bytes]] = None,
        **kwargs: Any,
    ) -> None:
        if "request_path" in kwargs:
            raise AuthorityValidationError(
                "relay transport request_path is fixed"
            )
        super().__init__(
            peer_links=peer_links,
            peer_destination_hashes=peer_destination_hashes,
            request_path=RETICULUM_WATERMARK_RELAY_PATH,
            **kwargs,
        )


class ReticulumRelayedWatermarkServer:
    """Bind one-hop relay admission to a Reticulum request handler."""

    def __init__(
        self,
        *,
        destination: Any,
        endpoint: RelayedWatermarkEndpoint,
        relay_identity_hashes: Optional[Mapping[str, bytes]] = None,
    ) -> None:
        if not isinstance(endpoint, RelayedWatermarkEndpoint):
            raise AuthorityValidationError(
                "endpoint must be RelayedWatermarkEndpoint"
            )
        self.destination = destination
        self.endpoint = endpoint
        self.request_path = RETICULUM_WATERMARK_RELAY_PATH
        self.relay_identity_hashes = dict(relay_identity_hashes or {})
        for relay_id, identity_hash in self.relay_identity_hashes.items():
            _required(relay_id, "relay_id")
            if not isinstance(identity_hash, bytes) or not identity_hash:
                raise AuthorityValidationError(
                    "relay identity hashes must be non-empty bytes"
                )
        self._installed = False

    def install(
        self,
        *,
        allow: Any,
        allowed_list: Optional[list[Any]] = None,
        auto_compress: bool | int = True,
    ) -> None:
        if self._installed:
            raise ReticulumAdapterError(
                "Reticulum relay request handler already installed"
            )
        try:
            self.destination.register_request_handler(
                self.request_path,
                response_generator=self._handle_request,
                allow=allow,
                allowed_list=allowed_list,
                auto_compress=auto_compress,
            )
        except Exception as exc:
            raise ReticulumAdapterError(
                "Reticulum relay handler registration failed"
            ) from exc
        self._installed = True

    def _handle_request(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        del request_id, link_id, requested_at
        if path != self.request_path:
            raise ReticulumAdapterError(
                "unexpected Reticulum relay request path"
            )
        if not isinstance(data, bytes):
            raise ReticulumAdapterError(
                "Reticulum relay payload must be bytes"
            )

        envelope = decode_relayed_authenticated_watermark(data)
        expected_hash = self.relay_identity_hashes.get(envelope.relay_id)
        if expected_hash is None:
            raise ReticulumAdapterError("unbound ACP relay_id")
        if remote_identity is None:
            raise ReticulumAdapterError(
                "Reticulum remote identity required for relay"
            )
        actual_hash = getattr(remote_identity, "hash", None)
        if callable(actual_hash):
            actual_hash = actual_hash()
        if not isinstance(actual_hash, bytes) or not actual_hash:
            raise ReticulumAdapterError(
                "Reticulum remote identity hash unavailable"
            )
        if actual_hash != expected_hash:
            raise ReticulumAdapterError(
                "Reticulum identity does not match ACP relay_id"
            )
        return self.endpoint.receive(
            data,
            authenticated_relay_id=envelope.relay_id,
        )



class ReticulumSignedRelayChainTransport(ReticulumAuthoritySyncTransport):
    """Carry complete signed ACP relay-chain bytes over Reticulum."""

    def __init__(
        self,
        peer_links: Mapping[str, Any],
        peer_destination_hashes: Optional[Mapping[str, bytes]] = None,
        **kwargs: Any,
    ) -> None:
        if "request_path" in kwargs:
            raise AuthorityValidationError(
                "relay-chain transport request_path is fixed"
            )
        super().__init__(
            peer_links=peer_links,
            peer_destination_hashes=peer_destination_hashes,
            request_path=RETICULUM_WATERMARK_RELAY_CHAIN_PATH,
            **kwargs,
        )


class ReticulumSignedRelayChainServer:
    """Bind signed relay-chain admission to a Reticulum request handler."""

    def __init__(
        self,
        *,
        destination: Any,
        endpoint: Ed25519RelayChainEndpoint,
        terminal_relay_identity_hashes: Optional[Mapping[str, bytes]] = None,
    ) -> None:
        if not isinstance(endpoint, Ed25519RelayChainEndpoint):
            raise AuthorityValidationError(
                "endpoint must be Ed25519RelayChainEndpoint"
            )
        self.destination = destination
        self.endpoint = endpoint
        self.request_path = RETICULUM_WATERMARK_RELAY_CHAIN_PATH
        self.terminal_relay_identity_hashes = dict(
            terminal_relay_identity_hashes or {}
        )
        for relay_id, identity_hash in self.terminal_relay_identity_hashes.items():
            _required(relay_id, "relay_id")
            if not isinstance(identity_hash, bytes) or not identity_hash:
                raise AuthorityValidationError(
                    "terminal relay identity hashes must be non-empty bytes"
                )
        self._installed = False

    def install(
        self,
        *,
        allow: Any,
        allowed_list: Optional[list[Any]] = None,
        auto_compress: bool | int = True,
    ) -> None:
        if self._installed:
            raise ReticulumAdapterError(
                "Reticulum relay-chain request handler already installed"
            )
        try:
            self.destination.register_request_handler(
                self.request_path,
                response_generator=self._handle_request,
                allow=allow,
                allowed_list=allowed_list,
                auto_compress=auto_compress,
            )
        except Exception as exc:
            raise ReticulumAdapterError(
                "Reticulum relay-chain handler registration failed"
            ) from exc
        self._installed = True

    def _handle_request(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        del request_id, link_id, requested_at
        if path != self.request_path:
            raise ReticulumAdapterError(
                "unexpected Reticulum relay-chain request path"
            )
        if not isinstance(data, bytes):
            raise ReticulumAdapterError(
                "Reticulum relay-chain payload must be bytes"
            )

        chain = decode_ed25519_relay_chain(data)
        if not chain.hops:
            raise ReticulumAdapterError(
                "Reticulum relay-chain requires at least one hop"
            )
        terminal_relay_id = chain.hops[-1].relay_id
        expected_hash = self.terminal_relay_identity_hashes.get(
            terminal_relay_id
        )
        if expected_hash is None:
            raise ReticulumAdapterError(
                "unbound ACP terminal relay_id"
            )
        if remote_identity is None:
            raise ReticulumAdapterError(
                "Reticulum remote identity required for relay chain"
            )
        actual_hash = getattr(remote_identity, "hash", None)
        if callable(actual_hash):
            actual_hash = actual_hash()
        if not isinstance(actual_hash, bytes) or not actual_hash:
            raise ReticulumAdapterError(
                "Reticulum remote identity hash unavailable"
            )
        if actual_hash != expected_hash:
            raise ReticulumAdapterError(
                "Reticulum identity does not match terminal ACP relay_id"
            )
        return self.endpoint.receive(data)
