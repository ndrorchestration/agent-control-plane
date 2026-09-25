import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermark,
    AuthoritySyncWatermarkRegistry,
    WatermarkDisposition,
    decode_authority_sync_watermark_acknowledgement,
    encode_authority_sync_watermark,
)
from agent_control_plane.watermark_transport import (
    AuthoritySyncWatermarkEndpoint,
    LoopbackAuthoritySyncWatermarkTransport,
)


def record(watermark_id="wm-1", sequence=3):
    return AuthoritySyncWatermark(
        watermark_id=watermark_id,
        issuer_id="peer-a",
        target_sender_id="authority-source",
        min_sequence=sequence,
        issued_at="2026-09-25T15:02:00Z",
    )


def endpoint():
    return AuthoritySyncWatermarkEndpoint(
        receiver_id="node-b",
        registry=AuthoritySyncWatermarkRegistry(
            {"authority-source": {"peer-a"}}
        ),
    )


def test_loopback_watermark_exchange_applies_and_acknowledges():
    remote = endpoint()
    transport = LoopbackAuthoritySyncWatermarkTransport()
    transport.register("node-b", remote)

    ack = decode_authority_sync_watermark_acknowledgement(
        transport.exchange("node-b", encode_authority_sync_watermark(record()))
    )

    assert ack.disposition is WatermarkDisposition.APPLIED
    assert ack.receiver_id == "node-b"
    assert ack.min_sequence == 3
    assert remote.registry.required_sequence("authority-source") == 3


def test_exact_duplicate_is_acknowledged_as_duplicate():
    remote = endpoint()
    transport = LoopbackAuthoritySyncWatermarkTransport()
    transport.register("node-b", remote)
    payload = encode_authority_sync_watermark(record())

    first = decode_authority_sync_watermark_acknowledgement(
        transport.exchange("node-b", payload)
    )
    duplicate = decode_authority_sync_watermark_acknowledgement(
        transport.exchange("node-b", payload)
    )

    assert first.disposition is WatermarkDisposition.APPLIED
    assert duplicate.disposition is WatermarkDisposition.DUPLICATE


def test_untrusted_watermark_fails_closed_without_ack():
    remote = AuthoritySyncWatermarkEndpoint(
        receiver_id="node-b",
        registry=AuthoritySyncWatermarkRegistry(
            {"authority-source": {"peer-a"}}
        ),
    )
    transport = LoopbackAuthoritySyncWatermarkTransport()
    transport.register("node-b", remote)
    bad = AuthoritySyncWatermark(
        "wm-x",
        "peer-x",
        "authority-source",
        99,
        "2026-09-25T15:02:00Z",
    )

    with pytest.raises(AuthorityValidationError, match="untrusted"):
        transport.exchange("node-b", encode_authority_sync_watermark(bad))
    assert remote.registry.required_sequence("authority-source") is None


def test_watermark_regression_fails_closed():
    remote = endpoint()
    transport = LoopbackAuthoritySyncWatermarkTransport()
    transport.register("node-b", remote)
    transport.exchange("node-b", encode_authority_sync_watermark(record(sequence=4)))

    with pytest.raises(AuthorityValidationError, match="regression"):
        transport.exchange(
            "node-b",
            encode_authority_sync_watermark(record(watermark_id="wm-2", sequence=3)),
        )
    assert remote.registry.required_sequence("authority-source") == 4


def test_duplicate_peer_registration_and_unknown_peer_fail_closed():
    transport = LoopbackAuthoritySyncWatermarkTransport()
    remote = endpoint()
    transport.register("node-b", remote)
    with pytest.raises(AuthorityValidationError, match="already registered"):
        transport.register("node-b", remote)
    with pytest.raises(AuthorityValidationError, match="unknown watermark peer"):
        transport.exchange("missing", encode_authority_sync_watermark(record()))
