from agent_control_plane.authority_state import (
    AuthorityStateRequirement,
    AuthorityStateSnapshot,
    AuthorityStateStatus,
    InMemoryAuthorityStateCache,
)
from experiments.authority_partition import PartitionNode, simulate_partition


def node(node_id, snapshot=None):
    cache = InMemoryAuthorityStateCache()
    if snapshot is not None:
        cache.update(snapshot)
    return PartitionNode(node_id, cache)


def test_partitioned_nodes_diverge_but_stale_node_fails_closed():
    fresh = node(
        "node-a",
        AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:04:30Z", "authority-source"),
    )
    stale = node(
        "node-b",
        AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:04:50Z", "authority-source"),
    )

    decisions = simulate_partition(
        (fresh, stale),
        authority_id="auth-1",
        observed_at="2026-09-25T14:05:00Z",
        requirement=AuthorityStateRequirement(min_epoch=2, max_age_seconds=300),
    )

    by_node = {decision.node_id: decision for decision in decisions}
    assert by_node["node-a"].allowed is True
    assert by_node["node-a"].state.status is AuthorityStateStatus.CURRENT
    assert by_node["node-b"].allowed is False
    assert by_node["node-b"].state.status is AuthorityStateStatus.STALE_EPOCH


def test_partitioned_node_eventually_fails_on_age_even_without_new_epoch_floor():
    isolated = node(
        "node-b",
        AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:00:00Z", "authority-source"),
    )

    decision = simulate_partition(
        (isolated,),
        authority_id="auth-1",
        observed_at="2026-09-25T14:05:01Z",
        requirement=AuthorityStateRequirement(min_epoch=2, max_age_seconds=300),
    )[0]

    assert decision.allowed is False
    assert decision.state.status is AuthorityStateStatus.STALE_AGE


def test_reconciliation_to_newer_epoch_restores_local_eligibility():
    reconnecting = node(
        "node-b",
        AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:00:00Z", "authority-source"),
    )
    requirement = AuthorityStateRequirement(min_epoch=2, max_age_seconds=300)

    before = simulate_partition(
        (reconnecting,),
        authority_id="auth-1",
        observed_at="2026-09-25T14:04:00Z",
        requirement=requirement,
    )[0]
    assert before.allowed is False

    reconnecting.cache.update(
        AuthorityStateSnapshot("auth-1", 2, "2026-09-25T14:04:30Z", "authority-source")
    )
    after = simulate_partition(
        (reconnecting,),
        authority_id="auth-1",
        observed_at="2026-09-25T14:05:00Z",
        requirement=requirement,
    )[0]
    assert after.allowed is True
    assert after.state.status is AuthorityStateStatus.CURRENT


def test_missing_state_fails_closed():
    decision = simulate_partition(
        (node("node-c"),),
        authority_id="auth-1",
        observed_at="2026-09-25T14:05:00Z",
        requirement=AuthorityStateRequirement(min_epoch=1, max_age_seconds=300),
    )[0]
    assert decision.allowed is False
    assert decision.state.status is AuthorityStateStatus.MISSING
