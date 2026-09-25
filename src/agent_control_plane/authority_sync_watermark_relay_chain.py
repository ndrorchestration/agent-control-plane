"""Provenance-preserving Ed25519 relay-chain profile for ACP watermarks."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Mapping, Sequence

from .authority import AuthorityValidationError
from .authority_sync_watermark import (
    AuthoritySyncWatermark,
    AuthoritySyncWatermarkAcknowledgement,
    AuthoritySyncWatermarkRegistry,
    encode_authority_sync_watermark_acknowledgement,
)
from .authority_sync_watermark_ed25519 import (
    Ed25519AuthoritySyncWatermarkVerifier,
    decode_ed25519_authority_sync_watermark,
)
from .authority_sync_watermark_keys import (
    WatermarkAuthenticationKeyRegistry,
    WatermarkKeyStatus,
)


RELAY_CHAIN_SCHEMA_VERSION = (
    "agent-control-plane.authority-sync-watermark-relay-chain.v0-candidate"
)
RELAY_HOP_SCHEMA_VERSION = (
    "agent-control-plane.authority-sync-watermark-relay-hop.v0-candidate"
)
RELAY_HOP_ALGORITHM = "ed25519"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _canonical_utc(value: str, field_name: str) -> str:
    _required(value, field_name)
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AuthorityValidationError(f"{field_name} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(f"{field_name} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise AuthorityValidationError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(value: str, field_name: str) -> datetime:
    return datetime.fromisoformat(
        _canonical_utc(value, field_name).replace("Z", "+00:00")
    )


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise AuthorityValidationError(
            f"{field_name} must be a 64-character SHA-256 hex digest"
        )
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise AuthorityValidationError(
            f"{field_name} must be hexadecimal"
        ) from exc
    return value.lower()


def _load_ed25519():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise AuthorityValidationError(
            "Ed25519 relay-chain support requires the 'crypto' extra"
        ) from exc
    return InvalidSignature, Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class RelayHopAttestation:
    relay_id: str
    key_id: str
    hop_index: int
    relayed_at: str
    previous_sha256: str
    next_receiver_id: str
    algorithm: str
    signature_b64: str
    schema_version: str = RELAY_HOP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "relay_id", _required(self.relay_id, "relay_id"))
        object.__setattr__(self, "key_id", _required(self.key_id, "key_id"))
        if (
            isinstance(self.hop_index, bool)
            or not isinstance(self.hop_index, int)
            or self.hop_index < 0
        ):
            raise AuthorityValidationError("hop_index must be an integer >= 0")
        object.__setattr__(
            self,
            "relayed_at",
            _canonical_utc(self.relayed_at, "relayed_at"),
        )
        object.__setattr__(
            self,
            "previous_sha256",
            _validate_sha256(self.previous_sha256, "previous_sha256"),
        )
        object.__setattr__(
            self,
            "next_receiver_id",
            _required(self.next_receiver_id, "next_receiver_id"),
        )
        if self.algorithm != RELAY_HOP_ALGORITHM:
            raise AuthorityValidationError(
                f"unsupported relay hop algorithm: {self.algorithm}"
            )
        if not isinstance(self.signature_b64, str) or not self.signature_b64:
            raise AuthorityValidationError("signature_b64 must not be blank")
        try:
            signature = base64.b64decode(
                self.signature_b64.encode("ascii"),
                validate=True,
            )
        except Exception as exc:
            raise AuthorityValidationError(
                "signature_b64 must be valid base64"
            ) from exc
        if len(signature) != 64:
            raise AuthorityValidationError(
                "Ed25519 relay-hop signature must be 64 bytes"
            )
        if self.schema_version != RELAY_HOP_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "relay_id": self.relay_id,
            "key_id": self.key_id,
            "hop_index": self.hop_index,
            "relayed_at": self.relayed_at,
            "previous_sha256": self.previous_sha256,
            "next_receiver_id": self.next_receiver_id,
            "algorithm": self.algorithm,
            "signature_b64": self.signature_b64,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class Ed25519WatermarkRelayChain:
    origin_envelope_b64: str
    hops: tuple[RelayHopAttestation, ...]
    schema_version: str = RELAY_CHAIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.origin_envelope_b64, str) or not self.origin_envelope_b64:
            raise AuthorityValidationError(
                "origin_envelope_b64 must not be blank"
            )
        try:
            origin = base64.b64decode(
                self.origin_envelope_b64.encode("ascii"),
                validate=True,
            )
        except Exception as exc:
            raise AuthorityValidationError(
                "origin_envelope_b64 must be valid base64"
            ) from exc
        if not origin:
            raise AuthorityValidationError(
                "origin envelope must not be empty"
            )
        if not isinstance(self.hops, tuple):
            raise AuthorityValidationError("hops must be a tuple")
        if not all(isinstance(hop, RelayHopAttestation) for hop in self.hops):
            raise AuthorityValidationError(
                "all hops must be RelayHopAttestation"
            )
        if self.schema_version != RELAY_CHAIN_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def origin_payload(self) -> bytes:
        return base64.b64decode(
            self.origin_envelope_b64.encode("ascii"),
            validate=True,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "origin_envelope_b64": self.origin_envelope_b64,
            "hops": [hop.to_dict() for hop in self.hops],
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class VerifiedRelayChain:
    watermark: AuthoritySyncWatermark
    relay_path: tuple[str, ...]
    final_receiver_id: str


def new_ed25519_relay_chain(origin_payload: bytes) -> Ed25519WatermarkRelayChain:
    if not isinstance(origin_payload, bytes) or not origin_payload:
        raise AuthorityValidationError(
            "origin_payload must be non-empty bytes"
        )
    return Ed25519WatermarkRelayChain(
        origin_envelope_b64=base64.b64encode(origin_payload).decode("ascii"),
        hops=(),
    )


def _unsigned_hop_dict(
    *,
    relay_id: str,
    key_id: str,
    hop_index: int,
    relayed_at: str,
    previous_sha256: str,
    next_receiver_id: str,
) -> dict[str, object]:
    return {
        "relay_id": _required(relay_id, "relay_id"),
        "key_id": _required(key_id, "key_id"),
        "hop_index": hop_index,
        "relayed_at": _canonical_utc(relayed_at, "relayed_at"),
        "previous_sha256": _validate_sha256(
            previous_sha256,
            "previous_sha256",
        ),
        "next_receiver_id": _required(
            next_receiver_id,
            "next_receiver_id",
        ),
        "algorithm": RELAY_HOP_ALGORITHM,
        "schema_version": RELAY_HOP_SCHEMA_VERSION,
    }


def _hop_signature_input(
    *,
    relay_id: str,
    key_id: str,
    hop_index: int,
    relayed_at: str,
    previous_sha256: str,
    next_receiver_id: str,
) -> bytes:
    return json.dumps(
        _unsigned_hop_dict(
            relay_id=relay_id,
            key_id=key_id,
            hop_index=hop_index,
            relayed_at=relayed_at,
            previous_sha256=previous_sha256,
            next_receiver_id=next_receiver_id,
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def encode_relay_hop(hop: RelayHopAttestation) -> bytes:
    if not isinstance(hop, RelayHopAttestation):
        raise AuthorityValidationError(
            "hop must be RelayHopAttestation"
        )
    return json.dumps(
        hop.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def append_ed25519_relay_hop(
    chain: Ed25519WatermarkRelayChain,
    *,
    relay_id: str,
    key_id: str,
    private_key_raw: bytes,
    relayed_at: str,
    next_receiver_id: str,
) -> Ed25519WatermarkRelayChain:
    if not isinstance(chain, Ed25519WatermarkRelayChain):
        raise AuthorityValidationError(
            "chain must be Ed25519WatermarkRelayChain"
        )
    relay = _required(relay_id, "relay_id")
    if relay in {hop.relay_id for hop in chain.hops}:
        raise AuthorityValidationError(
            "relay chain must not repeat a relay_id"
        )
    if not isinstance(private_key_raw, bytes) or len(private_key_raw) != 32:
        raise AuthorityValidationError(
            "Ed25519 private_key_raw must be exactly 32 bytes"
        )
    previous = (
        _sha256_hex(chain.origin_payload())
        if not chain.hops
        else _sha256_hex(encode_relay_hop(chain.hops[-1]))
    )
    hop_index = len(chain.hops)
    signature_input = _hop_signature_input(
        relay_id=relay,
        key_id=key_id,
        hop_index=hop_index,
        relayed_at=relayed_at,
        previous_sha256=previous,
        next_receiver_id=next_receiver_id,
    )
    _, PrivateKey, _ = _load_ed25519()
    try:
        signature = PrivateKey.from_private_bytes(
            private_key_raw
        ).sign(signature_input)
    except Exception as exc:
        raise AuthorityValidationError(
            "Ed25519 relay-hop signing failed"
        ) from exc

    hop = RelayHopAttestation(
        relay_id=relay,
        key_id=key_id,
        hop_index=hop_index,
        relayed_at=relayed_at,
        previous_sha256=previous,
        next_receiver_id=next_receiver_id,
        algorithm=RELAY_HOP_ALGORITHM,
        signature_b64=base64.b64encode(signature).decode("ascii"),
    )
    return Ed25519WatermarkRelayChain(
        origin_envelope_b64=chain.origin_envelope_b64,
        hops=chain.hops + (hop,),
    )


def encode_ed25519_relay_chain(
    chain: Ed25519WatermarkRelayChain,
) -> bytes:
    if not isinstance(chain, Ed25519WatermarkRelayChain):
        raise AuthorityValidationError(
            "chain must be Ed25519WatermarkRelayChain"
        )
    return json.dumps(
        chain.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_ed25519_relay_chain(
    payload: bytes | str,
) -> Ed25519WatermarkRelayChain:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthorityValidationError(
                "relay-chain payload must be valid UTF-8"
            ) from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise AuthorityValidationError(
            "relay-chain payload must be bytes or str"
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthorityValidationError(
            "relay-chain payload must be valid JSON"
        ) from exc
    if not isinstance(data, Mapping):
        raise AuthorityValidationError(
            "relay-chain payload must decode to an object"
        )
    expected = {"origin_envelope_b64", "hops", "schema_version"}
    if set(data) != expected:
        raise AuthorityValidationError(
            "relay-chain payload keys mismatch"
        )
    raw_hops = data["hops"]
    if not isinstance(raw_hops, list):
        raise AuthorityValidationError("hops must be a list")
    hops = tuple(
        RelayHopAttestation(**hop)
        if isinstance(hop, Mapping)
        else (_ for _ in ()).throw(
            AuthorityValidationError("relay hop must be an object")
        )
        for hop in raw_hops
    )
    return Ed25519WatermarkRelayChain(
        origin_envelope_b64=data["origin_envelope_b64"],
        hops=hops,
        schema_version=data["schema_version"],
    )


class Ed25519RelayChainVerifier:
    """Verify origin signature plus every hash-linked relay-hop signature."""

    def __init__(
        self,
        *,
        origin_verifier: Ed25519AuthoritySyncWatermarkVerifier,
        relay_public_keys: Mapping[tuple[str, str], bytes],
        relay_key_registry: WatermarkAuthenticationKeyRegistry,
        max_hops: int = 16,
    ) -> None:
        if not isinstance(
            origin_verifier,
            Ed25519AuthoritySyncWatermarkVerifier,
        ):
            raise AuthorityValidationError(
                "origin_verifier must be Ed25519AuthoritySyncWatermarkVerifier"
            )
        if not isinstance(
            relay_key_registry,
            WatermarkAuthenticationKeyRegistry,
        ):
            raise AuthorityValidationError(
                "relay_key_registry must be WatermarkAuthenticationKeyRegistry"
            )
        if (
            isinstance(max_hops, bool)
            or not isinstance(max_hops, int)
            or max_hops < 1
        ):
            raise AuthorityValidationError(
                "max_hops must be an integer >= 1"
            )
        normalized: dict[tuple[str, str], bytes] = {}
        for raw_key, public_key_raw in relay_public_keys.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                raise AuthorityValidationError(
                    "relay public key mapping keys must be (relay_id, key_id)"
                )
            relay_id = _required(raw_key[0], "relay_id")
            key_id = _required(raw_key[1], "key_id")
            if (
                not isinstance(public_key_raw, bytes)
                or len(public_key_raw) != 32
            ):
                raise AuthorityValidationError(
                    "Ed25519 relay public keys must be exactly 32 bytes"
                )
            normalized[(relay_id, key_id)] = public_key_raw
        self.origin_verifier = origin_verifier
        self.relay_public_keys = normalized
        self.relay_key_registry = relay_key_registry
        self.max_hops = max_hops

    def verify(
        self,
        chain: Ed25519WatermarkRelayChain,
        *,
        final_receiver_id: str,
    ) -> VerifiedRelayChain:
        if not isinstance(chain, Ed25519WatermarkRelayChain):
            raise AuthorityValidationError(
                "chain must be Ed25519WatermarkRelayChain"
            )
        final_receiver = _required(
            final_receiver_id,
            "final_receiver_id",
        )
        if not chain.hops:
            raise AuthorityValidationError(
                "relay chain must contain at least one hop"
            )
        if len(chain.hops) > self.max_hops:
            raise AuthorityValidationError(
                "relay chain exceeds max_hops"
            )

        origin_envelope = decode_ed25519_authority_sync_watermark(
            chain.origin_payload()
        )
        watermark = self.origin_verifier.verify(origin_envelope)

        expected_previous = _sha256_hex(chain.origin_payload())
        seen_relays: set[str] = set()
        InvalidSignature, _, PublicKey = _load_ed25519()

        for index, hop in enumerate(chain.hops):
            if hop.hop_index != index:
                raise AuthorityValidationError(
                    "relay hop index mismatch"
                )
            if hop.relay_id in seen_relays:
                raise AuthorityValidationError(
                    "relay chain contains repeated relay_id"
                )
            seen_relays.add(hop.relay_id)
            if hop.previous_sha256 != expected_previous:
                raise AuthorityValidationError(
                    "relay hop previous hash mismatch"
                )

            expected_next = (
                chain.hops[index + 1].relay_id
                if index + 1 < len(chain.hops)
                else final_receiver
            )
            if hop.next_receiver_id != expected_next:
                raise AuthorityValidationError(
                    "relay hop next receiver mismatch"
                )

            record = self.relay_key_registry.get(
                hop.relay_id,
                hop.key_id,
            )
            if record is None:
                raise AuthorityValidationError(
                    "relay signing key lifecycle unknown"
                )
            if record.status is WatermarkKeyStatus.REVOKED:
                raise AuthorityValidationError(
                    "relay signing key revoked"
                )
            relayed_at = _utc(hop.relayed_at, "relayed_at")
            if relayed_at < _utc(record.valid_from, "valid_from"):
                raise AuthorityValidationError(
                    "relay signing key not yet valid"
                )
            if record.valid_until is not None and relayed_at >= _utc(
                record.valid_until,
                "valid_until",
            ):
                raise AuthorityValidationError(
                    "relay signing key expired"
                )

            public_key_raw = self.relay_public_keys.get(
                (hop.relay_id, hop.key_id)
            )
            if public_key_raw is None:
                raise AuthorityValidationError(
                    "unknown Ed25519 relay public key"
                )
            try:
                PublicKey.from_public_bytes(public_key_raw).verify(
                    base64.b64decode(
                        hop.signature_b64.encode("ascii"),
                        validate=True,
                    ),
                    _hop_signature_input(
                        relay_id=hop.relay_id,
                        key_id=hop.key_id,
                        hop_index=hop.hop_index,
                        relayed_at=hop.relayed_at,
                        previous_sha256=hop.previous_sha256,
                        next_receiver_id=hop.next_receiver_id,
                    ),
                )
            except InvalidSignature as exc:
                raise AuthorityValidationError(
                    "Ed25519 relay-hop signature verification failed"
                ) from exc
            except Exception as exc:
                raise AuthorityValidationError(
                    "Ed25519 relay-hop verification failed"
                ) from exc

            expected_previous = _sha256_hex(encode_relay_hop(hop))

        return VerifiedRelayChain(
            watermark=watermark,
            relay_path=tuple(hop.relay_id for hop in chain.hops),
            final_receiver_id=final_receiver,
        )



class Ed25519RelayChainEndpoint:
    """Verify a complete signed relay chain and apply its origin watermark."""

    def __init__(
        self,
        *,
        receiver_id: str,
        verifier: Ed25519RelayChainVerifier,
        registry: AuthoritySyncWatermarkRegistry,
    ) -> None:
        self.receiver_id = _required(receiver_id, "receiver_id")
        if not isinstance(verifier, Ed25519RelayChainVerifier):
            raise AuthorityValidationError(
                "verifier must be Ed25519RelayChainVerifier"
            )
        if not isinstance(registry, AuthoritySyncWatermarkRegistry):
            raise AuthorityValidationError(
                "registry must be AuthoritySyncWatermarkRegistry"
            )
        self.verifier = verifier
        self.registry = registry

    def receive(self, payload: bytes) -> bytes:
        if not isinstance(payload, bytes):
            raise AuthorityValidationError("payload must be bytes")
        chain = decode_ed25519_relay_chain(payload)
        verified = self.verifier.verify(
            chain,
            final_receiver_id=self.receiver_id,
        )
        watermark = verified.watermark
        disposition = self.registry.apply(watermark)
        return encode_authority_sync_watermark_acknowledgement(
            AuthoritySyncWatermarkAcknowledgement(
                watermark_id=watermark.watermark_id,
                issuer_id=watermark.issuer_id,
                receiver_id=self.receiver_id,
                target_sender_id=watermark.target_sender_id,
                min_sequence=watermark.min_sequence,
                disposition=disposition,
            )
        )



class Ed25519RelayChainAppender:
    """Verify an incoming chain prefix addressed to this relay, then append one hop."""

    def __init__(
        self,
        *,
        relay_id: str,
        key_id: str,
        private_key_raw: bytes,
        next_receiver_id: str,
        origin_verifier: Ed25519AuthoritySyncWatermarkVerifier,
        prefix_verifier: Ed25519RelayChainVerifier,
    ) -> None:
        self.relay_id = _required(relay_id, "relay_id")
        self.key_id = _required(key_id, "key_id")
        self.next_receiver_id = _required(
            next_receiver_id,
            "next_receiver_id",
        )
        if not isinstance(private_key_raw, bytes) or len(private_key_raw) != 32:
            raise AuthorityValidationError(
                "Ed25519 private_key_raw must be exactly 32 bytes"
            )
        if not isinstance(
            origin_verifier,
            Ed25519AuthoritySyncWatermarkVerifier,
        ):
            raise AuthorityValidationError(
                "origin_verifier must be Ed25519AuthoritySyncWatermarkVerifier"
            )
        if not isinstance(prefix_verifier, Ed25519RelayChainVerifier):
            raise AuthorityValidationError(
                "prefix_verifier must be Ed25519RelayChainVerifier"
            )
        self.private_key_raw = private_key_raw
        self.origin_verifier = origin_verifier
        self.prefix_verifier = prefix_verifier

    def append(
        self,
        chain: Ed25519WatermarkRelayChain,
        *,
        relayed_at: str,
    ) -> Ed25519WatermarkRelayChain:
        if not isinstance(chain, Ed25519WatermarkRelayChain):
            raise AuthorityValidationError(
                "chain must be Ed25519WatermarkRelayChain"
            )

        if chain.hops:
            self.prefix_verifier.verify(
                chain,
                final_receiver_id=self.relay_id,
            )
        else:
            origin_envelope = decode_ed25519_authority_sync_watermark(
                chain.origin_payload()
            )
            self.origin_verifier.verify(origin_envelope)

        return append_ed25519_relay_hop(
            chain,
            relay_id=self.relay_id,
            key_id=self.key_id,
            private_key_raw=self.private_key_raw,
            relayed_at=relayed_at,
            next_receiver_id=self.next_receiver_id,
        )
