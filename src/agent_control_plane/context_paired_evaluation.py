"""Fail-closed paired task evaluation for CEP dynamic-exposure experiments.

This layer does not perform model inference or tool execution. It records paired
control/treatment observations and refuses an end-to-end advancement result unless
dynamic model-visible exposure was directly observed for both arms.
"""

from __future__ import annotations

from dataclasses import dataclass


PAIRED_TASK_EVALUATION_SCHEMA = "agent-control-plane.paired-task-evaluation.v0-candidate"
PAIRED_ELIGIBLE = "ELIGIBLE_FOR_END_TO_END_ADVANCEMENT"
PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED = "BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED"
PAIRED_BLOCKED_PRESERVATION_FAILURE = "BLOCKED_PRESERVATION_FAILURE"
PAIRED_NO_MEASURED_REDUCTION = "NO_MEASURED_REDUCTION"


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class PairedTaskArm:
    """One control or treatment arm from a paired task evaluation."""

    catalog_sha256: str
    model_visible_exposure_observed: bool
    model_visible_tool_count: int | None
    model_visible_tool_tokens: int | None
    selected_tool: str
    normalized_result_sha256: str
    evidence_sha256: str
    acceptance: str
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        _non_empty(self.catalog_sha256, "catalog_sha256")
        _non_empty(self.selected_tool, "selected_tool")
        _non_empty(self.normalized_result_sha256, "normalized_result_sha256")
        _non_empty(self.evidence_sha256, "evidence_sha256")
        _non_empty(self.acceptance, "acceptance")
        for name in (
            "model_visible_tool_count",
            "model_visible_tool_tokens",
            "latency_ms",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if self.model_visible_exposure_observed:
            if self.model_visible_tool_count is None:
                raise ValueError(
                    "observed model-visible exposure requires model_visible_tool_count"
                )
            if self.model_visible_tool_tokens is None:
                raise ValueError(
                    "observed model-visible exposure requires model_visible_tool_tokens"
                )


@dataclass(frozen=True)
class PairedTaskEvaluation:
    """Paired control/treatment record with explicit preservation and exposure gates."""

    evaluation_id: str
    task_contract: str
    authority_boundaries_sha256: str
    control: PairedTaskArm
    treatment: PairedTaskArm

    def __post_init__(self) -> None:
        _non_empty(self.evaluation_id, "evaluation_id")
        _non_empty(self.task_contract, "task_contract")
        _non_empty(self.authority_boundaries_sha256, "authority_boundaries_sha256")
        if not isinstance(self.control, PairedTaskArm):
            raise TypeError("control must be PairedTaskArm")
        if not isinstance(self.treatment, PairedTaskArm):
            raise TypeError("treatment must be PairedTaskArm")

    def evaluate(self) -> dict[str, object]:
        reasons: list[str] = []

        if (
            not self.control.model_visible_exposure_observed
            or not self.treatment.model_visible_exposure_observed
        ):
            status = PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED
            reasons.append("MODEL_VISIBLE_DYNAMIC_EXPOSURE_NOT_OBSERVED")
        else:
            if self.control.selected_tool != self.treatment.selected_tool:
                reasons.append("SELECTED_TOOL_DRIFT")
            if (
                self.control.normalized_result_sha256
                != self.treatment.normalized_result_sha256
            ):
                reasons.append("NORMALIZED_RESULT_DRIFT")
            if self.control.evidence_sha256 != self.treatment.evidence_sha256:
                reasons.append("EVIDENCE_DRIFT")
            if self.control.acceptance != self.treatment.acceptance:
                reasons.append("ACCEPTANCE_DRIFT")

            if reasons:
                status = PAIRED_BLOCKED_PRESERVATION_FAILURE
            elif (
                self.control.model_visible_tool_tokens is None
                or self.treatment.model_visible_tool_tokens is None
            ):
                status = PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED
                reasons.append("MODEL_VISIBLE_TOOL_TOKENS_UNOBSERVED")
            elif (
                self.treatment.model_visible_tool_tokens
                >= self.control.model_visible_tool_tokens
            ):
                status = PAIRED_NO_MEASURED_REDUCTION
                reasons.append("MODEL_VISIBLE_TOOL_TOKENS_NOT_REDUCED")
            else:
                status = PAIRED_ELIGIBLE
                reasons.append(
                    "DYNAMIC_EXPOSURE_OBSERVED_PRESERVATION_PASS_AND_TOKENS_REDUCED"
                )

        return {
            "schema": PAIRED_TASK_EVALUATION_SCHEMA,
            "evaluation_id": self.evaluation_id,
            "task_contract": self.task_contract,
            "authority_boundaries_sha256": self.authority_boundaries_sha256,
            "status": status,
            "reasons": reasons,
            "control_catalog_sha256": self.control.catalog_sha256,
            "treatment_catalog_sha256": self.treatment.catalog_sha256,
            "control_model_visible_tool_count": self.control.model_visible_tool_count,
            "treatment_model_visible_tool_count": self.treatment.model_visible_tool_count,
            "control_model_visible_tool_tokens": self.control.model_visible_tool_tokens,
            "treatment_model_visible_tool_tokens": self.treatment.model_visible_tool_tokens,
            "selected_tool": self.control.selected_tool,
            "authority_effect": "NONE",
            "scientific_n_increment": 0,
            "efficacy_effect": "NONE",
            "independent_validation_effect": "NONE",
            "high_assurance_effect": "NONE",
        }
