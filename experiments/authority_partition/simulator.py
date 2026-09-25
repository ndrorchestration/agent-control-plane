"""Deterministic partition simulation for authority-state freshness behavior."""

from dataclasses import dataclass

from agent_control_plane.authority_state import (
    AuthorityStateEvaluation,
    AuthorityStateRequirement,
    InMemoryAuthorityStateCache,
)


@dataclass(frozen=True)
class NodeDecision:
    node_id: str
    authority_id: str
    allowed: bool
    state: AuthorityStateEvaluation


@dataclass
class PartitionNode:
    node_id: str
    cache: InMemoryAuthorityStateCache

    def evaluate(
        self,
        *,
        authority_id: str,
        observed_at: str,
        requirement: AuthorityStateRequirement,
    ) -> NodeDecision:
        state = self.cache.evaluate(authority_id, observed_at, requirement)
        return NodeDecision(
            node_id=self.node_id,
            authority_id=authority_id,
            allowed=state.current,
            state=state,
        )


def simulate_partition(
    nodes: tuple[PartitionNode, ...],
    *,
    authority_id: str,
    observed_at: str,
    requirement: AuthorityStateRequirement,
) -> tuple[NodeDecision, ...]:
    if not nodes:
        raise ValueError("nodes must not be empty")
    seen = set()
    decisions = []
    for node in nodes:
        if not isinstance(node, PartitionNode):
            raise TypeError("all nodes must be PartitionNode")
        if node.node_id in seen:
            raise ValueError("node_id values must be unique")
        seen.add(node.node_id)
        decisions.append(
            node.evaluate(
                authority_id=authority_id,
                observed_at=observed_at,
                requirement=requirement,
            )
        )
    return tuple(decisions)
