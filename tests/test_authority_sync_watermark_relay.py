import json

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermark,
    AuthoritySyncWatermarkRegistry,
    WatermarkDisposition,
)
from agent_control_plane.authority_sync_watermark_auth import (
    HmacAuthoritySyncWatermarkVerifier,
    authenticate_authority_sync_watermark,
    encode_authenticated_authority_sync_watermark,
)
from agent_control_plane.authority_sync_watermark_relay import (
    RelayedWatermarkAdmission,
    decode_relayed_authenticated_watermark,
    encode_relayed_authenticated_watermark,
    wrap_authenticated_watermark_for_relay,
)


KEY = b"k" * 32


def origin_watermark():
    return AuthoritySyncWatermark(
        watermark_id="peer-a:authority-source:3",
        issuer_id="peer-a",
        target_sender_id="authority-source",
        min_sequence=3,
        issued_at="2026-09-25T17:20:00Z",
    )


def origin_payload():
    return encode_authenticated_authority_sync_watermark(
        authenticate_authority_sync_watermark(
            origin_watermark(),
            key_id="key-1",
            key=KEY,
        )
    )


def admission():
    return RelayedWatermarkAdmission(
        verifier=HmacAuthoritySyncWatermarkVerifier(
            {("peer-a", "key-1"): KEY}
        ),
        registry=AuthoritySyncWatermarkRegistry(
            {"authority-source": {"peer-a"}}
        ),
    )


def test_relay_can_forward_without_origin_secret_and_final_receiver_applies():
    relayed = wrap_authenticated_watermark_for_relay(
        origin_payload(),
        relay_id="peer-b",
        relayed_at="2026-09-25T17:21:00Z",
    )
    encoded = encode_relayed_authenticated_watermark(relayed)
    decoded = decode_relayed_authenticated_watermark(encoded)

    target = admission()
    result = target.admit(
        decoded,
        authenticated_relay_id="peer-b",
    )
    assert result is WatermarkDisposition.APPLIED
    assert target.registry.required_sequence("authority-source") == 3


def test_relay_identity_mismatch_fails_before_origin_application():
    relayed = wrap_authenticated_watermark_for_relay(
        origin_payload(),
        relay_id="peer-b",
        relayed_at="2026-09-25T17:21:00Z",
    )
    target = admission()

    with pytest.raises(
        AuthorityValidationError,
        match="relay identity mismatch",
    ):
        target.admit(
            relayed,
            authenticated_relay_id="peer-c",
        )
    assert target.registry.required_sequence("authority-source") is None


def test_relay_origin_tampering_fails_hmac_verification():
    raw = json.loads(origin_payload())
    raw["watermark"]["min_sequence"] = 99
    tampered_origin = json.dumps(
        raw,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    relayed = wrap_authenticated_watermark_for_relay(
        tampered_origin,
        relay_id="peer-b",
        relayed_at="2026-09-25T17:21:00Z",
    )
    target = admission()

    with pytest.raises(
        AuthorityValidationError,
        match="authentication failed",
    ):
        target.admit(
            relayed,
            authenticated_relay_id="peer-b",
        )
    assert target.registry.required_sequence("authority-source") is None


def test_exact_relay_replay_is_idempotent_at_final_registry():
    relayed = wrap_authenticated_watermark_for_relay(
        origin_payload(),
        relay_id="peer-b",
        relayed_at="2026-09-25T17:21:00Z",
    )
    target = admission()

    assert target.admit(
        relayed,
        authenticated_relay_id="peer-b",
    ) is WatermarkDisposition.APPLIED
    assert target.admit(
        relayed,
        authenticated_relay_id="peer-b",
    ) is WatermarkDisposition.DUPLICATE


def test_unknown_origin_key_fails_closed():
    relayed = wrap_authenticated_watermark_for_relay(
        origin_payload(),
        relay_id="peer-b",
        relayed_at="2026-09-25T17:21:00Z",
    )
    target = RelayedWatermarkAdmission(
        verifier=HmacAuthoritySyncWatermarkVerifier({}),
        registry=AuthoritySyncWatermarkRegistry(
            {"authority-source": {"peer-a"}}
        ),
    )

    with pytest.raises(
        AuthorityValidationError,
        match="unknown watermark authentication key",
    ):
        target.admit(
            relayed,
            authenticated_relay_id="peer-b",
        )
