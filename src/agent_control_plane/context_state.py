"""Context Efficiency Plane candidate state primitives.

This module records compact working-state projections without treating them as
canonical evidence or authority. It intentionally performs no automatic
retrieval, compaction, routing, or execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence


CONTEXT_STATE_SCHEMA = "agent-control-plane.context-state.v0-candidate"


def _non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _string_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{field_name} must be a sequence of strings")
    result = tuple(_non_empty(value, field_name) for value in values)
    return result


@dataclass(frozen=True)
class EvidenceReference:
    """Pointer to canonical evidence; never a replacement for that evidence."""

    source: str
    identity: str
    locator: str | None = None
    authority_effect: str = "NONE"

    def __post_init__(self) -> None:
        _non_empty(self.source, "source")
        _non_empty(self.identity, "identity")
        _non_empty(self.authority_effect, "authority_effect")
        if self.locator is not None:
            _non_empty(self.locator, "locator")


@dataclass(frozen=True)
class ContextState:
    """Compact operating projection for checkpoint + delta continuation."""

    task_id: str
    objective: str
    authority_boundaries: tuple[str, ...] = field(default_factory=tuple)
    evidence: tuple[EvidenceReference, ...] = field(default_factory=tuple)
    unresolved: tuple[str, ...] = field(default_factory=tuple)
    recent_delta: tuple[str, ...] = field(default_factory=tuple)
    next_action: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.task_id, "task_id")
        _non_empty(self.objective, "objective")
        object.__setattr__(
            self,
            "authority_boundaries",
            _string_tuple(self.authority_boundaries, "authority_boundaries"),
        )
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(ref, EvidenceReference) for ref in self.evidence
        ):
            raise TypeError("evidence must be a tuple of EvidenceReference")
        object.__setattr__(
            self,
            "unresolved",
            _string_tuple(self.unresolved, "unresolved"),
        )
        object.__setattr__(
            self,
            "recent_delta",
            _string_tuple(self.recent_delta, "recent_delta"),
        )
        if self.next_action is not None:
            _non_empty(self.next_action, "next_action")


def context_state_to_mapping(state: ContextState) -> dict[str, Any]:
    """Return a deterministic, explicit representation of the working state."""
    if not isinstance(state, ContextState):
        raise TypeError("state must be ContextState")
    return {
        "schema": CONTEXT_STATE_SCHEMA,
        "task_id": state.task_id,
        "objective": state.objective,
        "authority_boundaries": list(state.authority_boundaries),
        "evidence": [
            {
                "source": ref.source,
                "identity": ref.identity,
                "locator": ref.locator,
                "authority_effect": ref.authority_effect,
            }
            for ref in state.evidence
        ],
        "unresolved": list(state.unresolved),
        "recent_delta": list(state.recent_delta),
        "next_action": state.next_action,
    }


def canonical_context_state_bytes(state: ContextState) -> bytes:
    """Canonical bytes for content identity; this is not authentication."""
    return json.dumps(
        context_state_to_mapping(state),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def context_state_sha256(state: ContextState) -> str:
    """Return deterministic SHA-256 content identity for a working-state projection."""
    return hashlib.sha256(canonical_context_state_bytes(state)).hexdigest()


def context_state_from_mapping(value: Mapping[str, Any]) -> ContextState:
    """Parse a strict v0 candidate mapping into ContextState."""
    if not isinstance(value, Mapping):
        raise TypeError("context state must be a mapping")
    expected = {
        "schema",
        "task_id",
        "objective",
        "authority_boundaries",
        "evidence",
        "unresolved",
        "recent_delta",
        "next_action",
    }
    if set(value) != expected:
        raise ValueError("context state fields mismatch")
    if value.get("schema") != CONTEXT_STATE_SCHEMA:
        raise ValueError("unsupported context state schema")

    raw_evidence = value.get("evidence")
    if not isinstance(raw_evidence, list):
        raise TypeError("evidence must be a list")
    evidence: list[EvidenceReference] = []
    for item in raw_evidence:
        if not isinstance(item, Mapping):
            raise TypeError("evidence entries must be mappings")
        required = {"source", "identity", "locator", "authority_effect"}
        if set(item) != required:
            raise ValueError("evidence reference fields mismatch")
        evidence.append(
            EvidenceReference(
                source=item["source"],
                identity=item["identity"],
                locator=item["locator"],
                authority_effect=item["authority_effect"],
            )
        )

    return ContextState(
        task_id=value["task_id"],
        objective=value["objective"],
        authority_boundaries=tuple(value["authority_boundaries"]),
        evidence=tuple(evidence),
        unresolved=tuple(value["unresolved"]),
        recent_delta=tuple(value["recent_delta"]),
        next_action=value["next_action"],
    )
