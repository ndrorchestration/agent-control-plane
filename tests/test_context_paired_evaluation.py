import pytest

from agent_control_plane.context_paired_evaluation import (
    PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED,
    PAIRED_BLOCKED_PRESERVATION_FAILURE,
    PAIRED_ELIGIBLE,
    PairedTaskArm,
    PairedTaskEvaluation,
)


def arm(*, observed: bool, count=None, tokens=None, result="result-a", evidence="ev-a"):
    return PairedTaskArm(
        catalog_sha256="catalog-a",
        model_visible_exposure_observed=observed,
        model_visible_tool_count=count,
        model_visible_tool_tokens=tokens,
        selected_tool="mcp__GitHub__fetch_commit_workflow_runs",
        normalized_result_sha256=result,
        evidence_sha256=evidence,
        acceptance="accepted",
        latency_ms=10,
    )


def evaluation(control, treatment):
    return PairedTaskEvaluation(
        evaluation_id="paired-001",
        task_contract="verify exact-head workflow status",
        authority_boundaries_sha256="authority-boundary-sha",
        control=control,
        treatment=treatment,
    )


def test_unobserved_dynamic_exposure_blocks_end_to_end_claim() -> None:
    result = evaluation(
        arm(observed=False),
        arm(observed=False),
    ).evaluate()

    assert result["status"] == PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED
    assert result["scientific_n_increment"] == 0
    assert result["efficacy_effect"] == "NONE"


def test_observed_equivalent_result_with_reduced_tokens_is_eligible() -> None:
    control = arm(observed=True, count=89, tokens=32471)
    treatment = arm(observed=True, count=1, tokens=268)
    treatment = PairedTaskArm(
        **{**treatment.__dict__, "catalog_sha256": "catalog-b"}
    )

    result = evaluation(control, treatment).evaluate()

    assert result["status"] == PAIRED_ELIGIBLE
    assert result["control_model_visible_tool_tokens"] == 32471
    assert result["treatment_model_visible_tool_tokens"] == 268


def test_result_or_evidence_drift_blocks_advancement() -> None:
    control = arm(observed=True, count=89, tokens=32471)
    treatment = arm(
        observed=True,
        count=1,
        tokens=268,
        result="result-b",
        evidence="ev-b",
    )

    result = evaluation(control, treatment).evaluate()

    assert result["status"] == PAIRED_BLOCKED_PRESERVATION_FAILURE
    assert "NORMALIZED_RESULT_DRIFT" in result["reasons"]
    assert "EVIDENCE_DRIFT" in result["reasons"]


def test_observed_exposure_requires_count_and_token_measurement() -> None:
    with pytest.raises(ValueError):
        arm(observed=True, count=1, tokens=None)



def test_unobserved_arm_keeps_unknown_fields_null() -> None:
    unknown = PairedTaskArm(
        catalog_sha256="catalog-unobserved",
        model_visible_exposure_observed=False,
    )
    result = evaluation(unknown, unknown).evaluate()

    assert result["status"] == PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED
    assert result["selected_tool"] is None
    assert result["control_model_visible_tool_tokens"] is None
    assert result["treatment_model_visible_tool_tokens"] is None
