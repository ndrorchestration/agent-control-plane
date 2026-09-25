import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.revocation import InMemoryRevocationRegistry, RevocationRecord


def test_revocation_registry_is_append_only_and_idempotent_for_same_record():
    registry = InMemoryRevocationRegistry()
    record = RevocationRecord("auth-1", "2026-09-25T14:00:00Z", "operator_revoked")
    registry.revoke(record)
    registry.revoke(record)
    assert registry.get("auth-1") == record
    assert registry.manifest()["record_count"] == 1


def test_conflicting_second_revocation_fails_closed():
    registry = InMemoryRevocationRegistry()
    registry.revoke(RevocationRecord("auth-1", "2026-09-25T14:00:00Z", "operator_revoked"))
    with pytest.raises(AuthorityValidationError, match="different record"):
        registry.revoke(RevocationRecord("auth-1", "2026-09-25T14:05:00Z", "other_reason"))


def test_revocation_applies_at_and_after_recorded_time_only():
    registry = InMemoryRevocationRegistry()
    registry.revoke(RevocationRecord("auth-1", "2026-09-25T14:00:00Z", "operator_revoked"))
    assert registry.is_revoked_at("auth-1", "2026-09-25T13:59:59Z") is False
    assert registry.is_revoked_at("auth-1", "2026-09-25T14:00:00Z") is True
    assert registry.is_revoked_at("auth-1", "2026-09-25T14:00:01Z") is True


def test_revocation_rejects_non_utc_times():
    with pytest.raises(AuthorityValidationError, match="UTC"):
        RevocationRecord("auth-1", "2026-09-25T10:00:00-04:00", "operator_revoked")


def test_manifest_is_deterministically_sorted_by_authority_id():
    registry = InMemoryRevocationRegistry()
    registry.revoke(RevocationRecord("auth-b", "2026-09-25T14:00:00Z", "b"))
    registry.revoke(RevocationRecord("auth-a", "2026-09-25T14:01:00Z", "a"))
    ids = [item["authority_id"] for item in registry.manifest()["records"]]
    assert ids == ["auth-a", "auth-b"]
