"""Non-authorizing paired live-task observations for CEP Experiment 2."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .context_baseline import BaselineObservation, baseline_observation_sha256
from .context_comparison import (
    ComparisonPlan,
    ComparisonResult,
    TreatmentObservation,
    evaluate_treatment,
)


PAIRED_TASK_RESULT_SCHEMA = "agent-control-plane.cep-paired-task-result.v0-candidate"
MEASUREMENT_BLOCKED = "MEASUREMENT_BLOCKED"


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class PairedTaskObservation:
    """Two externally executed observations under one frozen task/model contract."""

    pair_id: str
    model_identity: str
    config_identity: str
    control: BaselineObservation
    treatment: BaselineObservation
    primary_metric: str

    def __post_init__(self) -> None:
        _non_empty(self.pair_id, "pair_id")
        _non_empty(self.model_identity, "model_identity")
        _non_empty(self.config_identity, "config_identity")
        _non_empty(self.primary_metric, "primary_metric")
        if not isinstance(self.control, BaselineObservation):
            raise TypeError("control must be BaselineObservation")
        if not isinstance(self.treatment, BaselineObservation):
            raise TypeError("treatment must be BaselineObservation")
        if self.control.task_contract != self.treatment.task_contract:
            raise ValueError("paired observations must share the exact task contract")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": PAIRED_TASK_RESULT_SCHEMA,
            "pair_id": self.pair_id,
            "model_identity": self.model_identity,
            "config_identity": self.config_identity,
            "primary_metric": self.primary_metric,
            "control_observation_sha256": baseline_observation_sha256(self.control),
            "treatment_observation_sha256": baseline_observation_sha256(
                self.treatment
            ),
        }


def paired_task_sha256(pair: PairedTaskObservation) -> str:
    payload = json.dumps(
        pair.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evaluate_paired_task(pair: PairedTaskObservation) -> dict[str, object]:
    """Adjudicate observed pair data without selecting or invoking any tool."""

    if not isinstance(pair, PairedTaskObservation):
        raise TypeError("pair must be PairedTaskObservation")

    plan = ComparisonPlan(
        plan_id=f"{pair.pair_id}-comparison",
        baseline=pair.control,
        treatment="externally_preselected_exact_capability_descriptor_set",
        primary_metric=pair.primary_metric,
        preservation_checks=(
            "same task contract",
            "same task identity and objective",
            "same authority boundaries",
            "same canonical evidence references",
            "same outcome and acceptance",
            "same model identity",
            "same config identity",
        ),
        acceptance_rule=(
            "directly observed primary metric decreases without preservation drift"
        ),
    )
    treatment = TreatmentObservation(
        task_contract=pair.treatment.task_contract,
        context_state=pair.treatment.context_state,
        telemetry=pair.treatment.telemetry,
        outcome=pair.treatment.outcome,
        acceptance=pair.treatment.acceptance,
    )
    result: ComparisonResult = evaluate_treatment(plan, treatment)

    disposition = result.status
    if result.status == "INCONCLUSIVE_UNOBSERVED_METRIC":
        disposition = MEASUREMENT_BLOCKED

    return {
        **pair.to_mapping(),
        "pair_sha256": paired_task_sha256(pair),
        "disposition": disposition,
        "comparison": result.to_mapping(),
        "execution_effect": "NONE",
        "routing_effect": "NONE",
        "automatic_tool_selection": "DISABLED",
        "claim_boundary": (
            "Bounded live-task characterization only; no generalized efficiency, "
            "efficacy, scientific-N, independent-validation, production-routing, "
            "execution-authority, or High-Assurance effect."
        ),
    }
