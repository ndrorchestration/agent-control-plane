import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_key_binding import (
    AuthorityKeyBindingRegistry,
    AuthorityKeyBindingStatus,
    binding_from_public_key,
)


PUB = bytes(range(32))
TRANSPORT = b"reticulum-identity-hash"


def record(**overrides):
    values = dict(
        binding_id="binding-1",
        subject_id="peer-a",
        key_id="ed-key-1",
        public_key_raw=PUB,
        transport_identity_raw=TRANSPORT,
        valid_from="2026-09-25T17:00:00Z",
        valid_until="2026-09-25T19:00:00Z",
    )
    values.update(overrides)
    return binding_from_public_key(**values)


def test_bound_public_key_and_transport_identity_verify():
    registry = AuthorityKeyBindingRegistry()
    registry.register(record())
    verified = registry.verify(
        subject_id="peer-a",
        key_id="ed-key-1",
        public_key_raw=PUB,
        transport_identity_raw=TRANSPORT,
        observed_at="2026-09-25T18:00:00Z",
    )
    assert verified.binding_id == "binding-1"


def test_wrong_public_key_fails_closed():
    registry = AuthorityKeyBindingRegistry()
    registry.register(record())
    with pytest.raises(AuthorityValidationError, match="public key binding mismatch"):
        registry.verify(
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=b"x" * 32,
            transport_identity_raw=TRANSPORT,
            observed_at="2026-09-25T18:00:00Z",
        )


def test_wrong_or_missing_transport_identity_fails_closed():
    registry = AuthorityKeyBindingRegistry()
    registry.register(record())
    with pytest.raises(AuthorityValidationError, match="transport identity binding mismatch"):
        registry.verify(
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=PUB,
            transport_identity_raw=b"other",
            observed_at="2026-09-25T18:00:00Z",
        )
    with pytest.raises(AuthorityValidationError, match="transport identity required"):
        registry.verify(
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=PUB,
            observed_at="2026-09-25T18:00:00Z",
        )


def test_binding_window_and_revocation_fail_closed():
    registry = AuthorityKeyBindingRegistry()
    registry.register(record())
    with pytest.raises(AuthorityValidationError, match="not yet valid"):
        registry.verify(
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=PUB,
            transport_identity_raw=TRANSPORT,
            observed_at="2026-09-25T16:59:59Z",
        )
    with pytest.raises(AuthorityValidationError, match="expired"):
        registry.verify(
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=PUB,
            transport_identity_raw=TRANSPORT,
            observed_at="2026-09-25T19:00:00Z",
        )

    revoked = registry.revoke(
        subject_id="peer-a",
        key_id="ed-key-1",
        revoked_at="2026-09-25T18:30:00Z",
    )
    assert revoked.status is AuthorityKeyBindingStatus.REVOKED
    with pytest.raises(AuthorityValidationError, match="binding revoked"):
        registry.verify(
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=PUB,
            transport_identity_raw=TRANSPORT,
            observed_at="2026-09-25T18:15:00Z",
        )


def test_subject_key_conflict_and_binding_id_conflict_fail_closed():
    registry = AuthorityKeyBindingRegistry()
    registry.register(record())

    with pytest.raises(AuthorityValidationError, match="subject/key binding conflict"):
        registry.register(
            record(
                binding_id="binding-2",
                public_key_raw=b"x" * 32,
            )
        )

    conflicting_id = binding_from_public_key(
        binding_id="binding-1",
        subject_id="peer-b",
        key_id="ed-key-2",
        public_key_raw=b"y" * 32,
        valid_from="2026-09-25T17:00:00Z",
    )
    with pytest.raises(AuthorityValidationError, match="binding_id conflict"):
        registry.register(conflicting_id)


def test_transport_binding_is_optional_when_not_provisioned():
    registry = AuthorityKeyBindingRegistry()
    registry.register(
        record(transport_identity_raw=None)
    )
    assert registry.verify(
        subject_id="peer-a",
        key_id="ed-key-1",
        public_key_raw=PUB,
        observed_at="2026-09-25T18:00:00Z",
    ).binding_id == "binding-1"


def test_manifest_contains_fingerprints_not_raw_key_material():
    registry = AuthorityKeyBindingRegistry()
    registry.register(record())
    manifest = registry.manifest()
    assert manifest["binding_count"] == 1
    serialized = str(manifest)
    assert str(PUB) not in serialized
    assert str(TRANSPORT) not in serialized



def test_bound_ed25519_verifier_requires_matching_public_and_transport_binding():
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from agent_control_plane.authority_key_binding import (
        BoundEd25519WatermarkVerifier,
    )
    from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermark
    from agent_control_plane.authority_sync_watermark_ed25519 import (
        sign_authority_sync_watermark_ed25519,
    )
    from agent_control_plane.authority_sync_watermark_keys import (
        WatermarkAuthenticationKeyRecord,
        WatermarkAuthenticationKeyRegistry,
    )

    private_raw = bytes(range(32))
    private = Ed25519PrivateKey.from_private_bytes(private_raw)
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    lifecycle = WatermarkAuthenticationKeyRegistry()
    lifecycle.register(
        WatermarkAuthenticationKeyRecord(
            issuer_id="peer-a",
            key_id="ed-key-1",
            valid_from="2026-09-25T17:00:00Z",
        )
    )

    bindings = AuthorityKeyBindingRegistry()
    bindings.register(
        binding_from_public_key(
            binding_id="binding-ed-1",
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=public_raw,
            transport_identity_raw=TRANSPORT,
            valid_from="2026-09-25T17:00:00Z",
        )
    )

    verifier = BoundEd25519WatermarkVerifier(
        public_keys={("peer-a", "ed-key-1"): public_raw},
        key_registry=lifecycle,
        binding_registry=bindings,
    )
    watermark = AuthoritySyncWatermark(
        watermark_id="wm-ed-1",
        issuer_id="peer-a",
        target_sender_id="authority-source",
        min_sequence=3,
        issued_at="2026-09-25T18:00:00Z",
    )
    envelope = sign_authority_sync_watermark_ed25519(
        watermark,
        key_id="ed-key-1",
        private_key_raw=private_raw,
    )

    assert verifier.verify(
        envelope,
        observed_at="2026-09-25T18:05:00Z",
        transport_identity_raw=TRANSPORT,
    ) == watermark

    with pytest.raises(
        AuthorityValidationError,
        match="transport identity binding mismatch",
    ):
        verifier.verify(
            envelope,
            observed_at="2026-09-25T18:05:00Z",
            transport_identity_raw=b"wrong-transport",
        )


def test_bound_ed25519_verifier_rejects_wrong_provisioned_public_key_before_signature():
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from agent_control_plane.authority_key_binding import (
        BoundEd25519WatermarkVerifier,
    )
    from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermark
    from agent_control_plane.authority_sync_watermark_ed25519 import (
        sign_authority_sync_watermark_ed25519,
    )
    from agent_control_plane.authority_sync_watermark_keys import (
        WatermarkAuthenticationKeyRecord,
        WatermarkAuthenticationKeyRegistry,
    )

    private_raw = bytes(range(32))
    private = Ed25519PrivateKey.from_private_bytes(private_raw)
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    wrong_private = Ed25519PrivateKey.from_private_bytes(b"x" * 32)
    wrong_public = wrong_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    lifecycle = WatermarkAuthenticationKeyRegistry()
    lifecycle.register(
        WatermarkAuthenticationKeyRecord(
            issuer_id="peer-a",
            key_id="ed-key-1",
            valid_from="2026-09-25T17:00:00Z",
        )
    )
    bindings = AuthorityKeyBindingRegistry()
    bindings.register(
        binding_from_public_key(
            binding_id="binding-ed-1",
            subject_id="peer-a",
            key_id="ed-key-1",
            public_key_raw=public_raw,
            valid_from="2026-09-25T17:00:00Z",
        )
    )

    verifier = BoundEd25519WatermarkVerifier(
        public_keys={("peer-a", "ed-key-1"): wrong_public},
        key_registry=lifecycle,
        binding_registry=bindings,
    )
    envelope = sign_authority_sync_watermark_ed25519(
        AuthoritySyncWatermark(
            watermark_id="wm-ed-1",
            issuer_id="peer-a",
            target_sender_id="authority-source",
            min_sequence=3,
            issued_at="2026-09-25T18:00:00Z",
        ),
        key_id="ed-key-1",
        private_key_raw=private_raw,
    )

    with pytest.raises(
        AuthorityValidationError,
        match="public key binding mismatch",
    ):
        verifier.verify(
            envelope,
            observed_at="2026-09-25T18:05:00Z",
        )
