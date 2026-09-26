import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.supervisor_ownership import (
    SupervisorOwnershipLeaseStore,
)


def test_acquire_and_renew_preserve_fencing_token(tmp_path):
    store = SupervisorOwnershipLeaseStore(tmp_path / "ownership.sqlite3")
    lease = store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-1",
        ownership_token="instance-1",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=10,
    )
    assert lease.fencing_token == 1

    renewed = store.renew(
        lease,
        now="2026-09-25T22:00:05Z",
        ttl_seconds=10,
    )
    assert renewed.fencing_token == 1
    assert renewed.expires_at == "2026-09-25T22:00:15Z"


def test_competing_owner_is_rejected_before_expiry(tmp_path):
    store = SupervisorOwnershipLeaseStore(tmp_path / "ownership.sqlite3")
    store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-1",
        ownership_token="instance-1",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=10,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="already held",
    ):
        store.acquire(
            resource_id="relay-a",
            owner_id="supervisor-2",
            ownership_token="instance-2",
            now="2026-09-25T22:00:05Z",
            ttl_seconds=10,
        )


def test_expired_lease_can_be_taken_over_with_higher_fence(tmp_path):
    store = SupervisorOwnershipLeaseStore(tmp_path / "ownership.sqlite3")
    old = store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-1",
        ownership_token="instance-1",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=10,
    )
    new = store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-2",
        ownership_token="instance-2",
        now="2026-09-25T22:00:10Z",
        ttl_seconds=10,
    )
    assert new.fencing_token == old.fencing_token + 1

    with pytest.raises(
        AuthorityValidationError,
        match="stale supervisor ownership lease",
    ):
        store.assert_current(
            old,
            now="2026-09-25T22:00:11Z",
        )
    with pytest.raises(
        AuthorityValidationError,
        match="stale supervisor ownership lease",
    ):
        store.renew(
            old,
            now="2026-09-25T22:00:11Z",
            ttl_seconds=10,
        )


def test_release_and_reacquire_increments_fence(tmp_path):
    store = SupervisorOwnershipLeaseStore(tmp_path / "ownership.sqlite3")
    first = store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-1",
        ownership_token="instance-1",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=10,
    )
    released = store.release(
        first,
        released_at="2026-09-25T22:00:01Z",
    )
    assert released.released_at == "2026-09-25T22:00:01Z"

    second = store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-2",
        ownership_token="instance-2",
        now="2026-09-25T22:00:02Z",
        ttl_seconds=10,
    )
    assert second.fencing_token == 2


def test_expired_lease_cannot_be_renewed(tmp_path):
    store = SupervisorOwnershipLeaseStore(tmp_path / "ownership.sqlite3")
    lease = store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-1",
        ownership_token="instance-1",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=5,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="expired",
    ):
        store.renew(
            lease,
            now="2026-09-25T22:00:05Z",
            ttl_seconds=5,
        )


def test_lease_persists_across_store_reopen(tmp_path):
    path = tmp_path / "ownership.sqlite3"
    first = SupervisorOwnershipLeaseStore(path)
    lease = first.acquire(
        resource_id="relay-a",
        owner_id="supervisor-1",
        ownership_token="instance-1",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=10,
    )

    reopened = SupervisorOwnershipLeaseStore(path)
    assert reopened.get("relay-a") == lease
    assert reopened.assert_current(
        lease,
        now="2026-09-25T22:00:01Z",
    ) == lease


def test_manifest_hashes_ownership_token(tmp_path):
    store = SupervisorOwnershipLeaseStore(tmp_path / "ownership.sqlite3")
    store.acquire(
        resource_id="relay-a",
        owner_id="supervisor-1",
        ownership_token="instance-secret-ish",
        now="2026-09-25T22:00:00Z",
        ttl_seconds=10,
    )
    manifest = store.manifest()
    assert manifest["lease_count"] == 1
    assert "instance-secret-ish" not in str(manifest)
    assert manifest["leases"][0]["fencing_token"] == 1
