import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_state import (
    AuthorityStateRequirement,
    AuthorityStateSnapshot,
    AuthorityStateStatus,
    InMemoryAuthorityStateCache,
)


def test_cache_accepts_monotonic_epoch_progression():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:00:00Z", "node-a"))
    cache.update(AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:01:00Z", "node-a"))
    assert cache.get("auth-1").epoch == 2


def test_epoch_regression_and_same_epoch_conflict_fail_closed():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:01:00Z", "node-a"))
    with pytest.raises(AuthorityValidationError, match="regression"):
        cache.update(AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:02:00Z", "node-a"))
    with pytest.raises(AuthorityValidationError, match="conflicting"):
        cache.update(AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:01:30Z", "node-b"))


def test_missing_snapshot_is_not_current():
    cache = InMemoryAuthorityStateCache()
    result = cache.evaluate(
        "auth-1", "2026-09-25T14:05:00Z", AuthorityStateRequirement(1, 300)
    )
    assert result.status is AuthorityStateStatus.MISSING
    assert result.current is False


def test_stale_epoch_is_detected_even_when_snapshot_is_recent():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:04:59Z", "node-a"))
    result = cache.evaluate(
        "auth-1", "2026-09-25T14:05:00Z", AuthorityStateRequirement(3, 300)
    )
    assert result.status is AuthorityStateStatus.STALE_EPOCH


def test_stale_age_is_detected_when_epoch_is_sufficient():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 3, "2026-09-25T14:00:00Z", "node-a"))
    result = cache.evaluate(
        "auth-1", "2026-09-25T14:05:01Z", AuthorityStateRequirement(3, 300)
    )
    assert result.status is AuthorityStateStatus.STALE_AGE


def test_future_snapshot_fails_closed():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 3, "2026-09-25T14:06:00Z", "node-a"))
    result = cache.evaluate(
        "auth-1", "2026-09-25T14:05:00Z", AuthorityStateRequirement(3, 300)
    )
    assert result.status is AuthorityStateStatus.FUTURE_STATE


def test_current_snapshot_requires_epoch_and_age_to_both_pass():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-1", 3, "2026-09-25T14:00:00Z", "node-a"))
    result = cache.evaluate(
        "auth-1", "2026-09-25T14:05:00Z", AuthorityStateRequirement(3, 300)
    )
    assert result.status is AuthorityStateStatus.CURRENT
    assert result.current is True


def test_manifest_is_deterministically_sorted():
    cache = InMemoryAuthorityStateCache()
    cache.update(AuthorityStateSnapshot("auth-b", 1, "2026-09-25T14:00:00Z", "node-b"))
    cache.update(AuthorityStateSnapshot("auth-a", 1, "2026-09-25T14:00:00Z", "node-a"))
    manifest = cache.manifest()
    assert manifest["schema"] == "agent-control-plane.authority-state.v0-candidate"
    assert [item["authority_id"] for item in manifest["snapshots"]] == ["auth-a", "auth-b"]
