"""Deterministic direct-peer convergence for ACP synchronization watermarks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .authority import AuthorityValidationError
from .authority_sync import AuthoritySyncReconciler
from .authority_sync_watermark import (
    AuthoritySyncWatermark,
    AuthoritySyncWatermarkRegistry,
    WatermarkDisposition,
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


@dataclass(frozen=True)
class WatermarkObservation:
    node_id: str
    target_sender_id: str
    observed_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _required(self.node_id, "node_id"))
        object.__setattr__(
            self,
            "target_sender_id",
            _required(self.target_sender_id, "target_sender_id"),
        )
        if (
            isinstance(self.observed_sequence, bool)
            or not isinstance(self.observed_sequence, int)
            or self.observed_sequence < 0
        ):
            raise AuthorityValidationError(
                "observed_sequence must be an integer >= 0"
            )


class AuthoritySyncWatermarkPublisher:
    """Issue watermarks only from sequence progress actually reconciled locally."""

    def __init__(self, *, node_id: str, reconciler: AuthoritySyncReconciler) -> None:
        self.node_id = _required(node_id, "node_id")
        if not isinstance(reconciler, AuthoritySyncReconciler):
            raise AuthorityValidationError(
                "reconciler must be AuthoritySyncReconciler"
            )
        self.reconciler = reconciler

    def observe(self, target_sender_id: str) -> WatermarkObservation | None:
        target = _required(target_sender_id, "target_sender_id")
        sender_sequences = self.reconciler.manifest().get("sender_sequences")
        if not isinstance(sender_sequences, dict):
            raise AuthorityValidationError(
                "reconciler sender sequence state unavailable"
            )
        sequence = sender_sequences.get(target)
        if not isinstance(sequence, int):
            return None
        return WatermarkObservation(self.node_id, target, sequence)

    def issue(
        self,
        *,
        target_sender_id: str,
        issued_at: str,
    ) -> AuthoritySyncWatermark | None:
        observation = self.observe(target_sender_id)
        if observation is None:
            return None
        return AuthoritySyncWatermark(
            watermark_id=(
                f"{self.node_id}:{observation.target_sender_id}:"
                f"{observation.observed_sequence}"
            ),
            issuer_id=self.node_id,
            target_sender_id=observation.target_sender_id,
            min_sequence=observation.observed_sequence,
            issued_at=issued_at,
        )


@dataclass
class DirectWatermarkPeer:
    """One node in a deterministic direct-peer watermark convergence harness."""

    node_id: str
    publisher: AuthoritySyncWatermarkPublisher
    registry: AuthoritySyncWatermarkRegistry

    def __post_init__(self) -> None:
        self.node_id = _required(self.node_id, "node_id")
        if self.publisher.node_id != self.node_id:
            raise AuthorityValidationError(
                "publisher node_id must match peer node_id"
            )
        if not isinstance(self.registry, AuthoritySyncWatermarkRegistry):
            raise AuthorityValidationError(
                "registry must be AuthoritySyncWatermarkRegistry"
            )


def converge_direct_watermarks(
    peers: Mapping[str, DirectWatermarkPeer],
    *,
    target_sender_id: str,
    issued_at: str,
    links: Iterable[tuple[str, str]],
) -> dict[tuple[str, str], WatermarkDisposition]:
    """Exchange fresh local observations across explicitly connected direct peers.

    Each directed link (source, destination) causes the source to issue a watermark
    derived only from its own reconciler progress. The destination applies that
    original source-issued watermark directly. This deliberately does not relay
    third-party claims and therefore does not model multi-hop propagation.
    """

    if not isinstance(peers, Mapping) or not peers:
        raise AuthorityValidationError("peers must be a non-empty mapping")
    target = _required(target_sender_id, "target_sender_id")
    results: dict[tuple[str, str], WatermarkDisposition] = {}

    for source_id, destination_id in links:
        source = peers.get(_required(source_id, "source_id"))
        destination = peers.get(_required(destination_id, "destination_id"))
        if source is None or destination is None:
            raise AuthorityValidationError("convergence link references unknown peer")
        if source.node_id == destination.node_id:
            raise AuthorityValidationError("convergence links must connect distinct peers")

        watermark = source.publisher.issue(
            target_sender_id=target,
            issued_at=issued_at,
        )
        if watermark is None:
            continue

        disposition = destination.registry.apply(watermark)
        results[(source.node_id, destination.node_id)] = disposition

    return results
