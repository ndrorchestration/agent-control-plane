"""Baseline observation records for Context Efficiency Plane characterization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .context_metrics import ContextTelemetry
from .context_state import ContextState, context_state_sha256


BASELINE_OBSERVATION_SCHEMA = "agent-control-plane.context-baseline-observation.v0-candidate"


def _non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class BaselineObservation:
    """One bounded task observation before optimization behavior is introduced."""

    observation_id: str
    task_contract: str
    context_state: ContextState
    telemetry: ContextTelemetry
    outcome: str
    acceptance: str
    notes: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.observation_id, "observation_id")
        _non_empty(self.task_contract, "task_contract")
        _non_empty(self.outcome, "outcome")
        _non_empty(self.acceptance, "acceptance")
        if not isinstance(self.context_state, ContextState):
            raise TypeError("context_state must be ContextState")
        if not isinstance(self.telemetry, ContextTelemetry):
            raise TypeError("telemetry must be ContextTelemetry")
        if self.notes is not None:
            _non_empty(self.notes, "notes")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": BASELINE_OBSERVATION_SCHEMA,
            "observation_id": self.observation_id,
            "task_contract": self.task_contract,
            "context_state_sha256": context_state_sha256(self.context_state),
            "telemetry": self.telemetry.to_mapping(),
            "outcome": self.outcome,
            "acceptance": self.acceptance,
            "notes": self.notes,
        }


def canonical_baseline_observation_bytes(observation: BaselineObservation) -> bytes:
    """Return deterministic bytes for control identity; this is not authentication."""
    if not isinstance(observation, BaselineObservation):
        raise TypeError("observation must be BaselineObservation")
    return json.dumps(
        observation.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def baseline_observation_sha256(observation: BaselineObservation) -> str:
    """Return deterministic SHA-256 identity for one frozen baseline observation."""
    return hashlib.sha256(canonical_baseline_observation_bytes(observation)).hexdigest()


def baseline_observation_from_mapping(
    value: Mapping[str, object],
    *,
    context_state: ContextState,
) -> BaselineObservation:
    """Rehydrate a record only when its supplied context state identity matches."""
    if not isinstance(value, Mapping):
        raise TypeError("observation must be a mapping")
    expected = {
        "schema",
        "observation_id",
        "task_contract",
        "context_state_sha256",
        "telemetry",
        "outcome",
        "acceptance",
        "notes",
    }
    if set(value) != expected:
        raise ValueError("baseline observation fields mismatch")
    if value.get("schema") != BASELINE_OBSERVATION_SCHEMA:
        raise ValueError("unsupported baseline observation schema")
    if value.get("context_state_sha256") != context_state_sha256(context_state):
        raise ValueError("context state identity mismatch")

    raw_telemetry = value.get("telemetry")
    if not isinstance(raw_telemetry, Mapping):
        raise TypeError("telemetry must be a mapping")

    input_fields = {
        "input_tokens",
        "output_tokens",
        "tool_result_tokens",
        "tool_definitions_exposed",
        "tools_invoked",
        "retrieved_tokens",
        "used_retrieved_tokens",
        "retrieved_items",
        "cacheable_prefix_tokens",
        "novel_prefix_tokens",
        "decision_relevant_input_tokens",
    }
    if not input_fields.issubset(raw_telemetry.keys()):
        raise ValueError("telemetry input fields mismatch")

    telemetry = ContextTelemetry(
        **{name: raw_telemetry[name] for name in input_fields}
    )
    return BaselineObservation(
        observation_id=value["observation_id"],
        task_contract=value["task_contract"],
        context_state=context_state,
        telemetry=telemetry,
        outcome=value["outcome"],
        acceptance=value["acceptance"],
        notes=value["notes"],
    )
