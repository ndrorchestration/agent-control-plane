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
from .sync_transport import AuthoritySyncEndpoint


RETICULUM_SYNC_PATH = "/ndrorchestration/acp/authority-sync/v0"


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
    request_path: str = RETICULUM_SYNC_PATH
    timeout_seconds: float = 15.0
    max_response_size: int = 65536
    poll_interval_seconds: float = 0.01
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        self.request_path = _required(self.request_path, "request_path")
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
    ) -> None:
        if not isinstance(endpoint, AuthoritySyncEndpoint):
            raise AuthorityValidationError("endpoint must be AuthoritySyncEndpoint")
        self.destination = destination
        self.endpoint = endpoint
        self.request_path = _required(request_path, "request_path")
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
        del request_id, link_id, remote_identity, requested_at
        if path != self.request_path:
            raise ReticulumAdapterError("unexpected Reticulum request path")
        if not isinstance(data, bytes):
            raise ReticulumAdapterError("Reticulum request payload must be bytes")
        return self.endpoint.receive(data)
