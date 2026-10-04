import json
from pathlib import Path

from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
    tool_catalog_snapshot_sha256,
)
from agent_control_plane.context_paired_evaluation import (
    PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED,
    PairedTaskArm,
    PairedTaskEvaluation,
)


CONTROL = Path(
    "experiments/context_efficiency/catalogs/github-connector-runtime-2026-10-04.json"
)
TREATMENT = Path(
    "experiments/context_efficiency/catalogs/github-status-treatment-2026-10-04.json"
)
RESULT = Path(
    "experiments/context_efficiency/results/"
    "github-status-dynamic-exposure-gap-2026-10-04.json"
)


def load_snapshot(path: Path):
    return tool_catalog_snapshot_from_mapping(
        json.loads(path.read_text(encoding="utf-8"))
    )


def test_frozen_dynamic_exposure_gap_is_reproducible() -> None:
    control = load_snapshot(CONTROL)
    treatment = load_snapshot(TREATMENT)

    evaluation = PairedTaskEvaluation(
        evaluation_id="github-status-dynamic-exposure-001",
        task_contract=(
            "Verify exact-head workflow status with equivalent evidence and acceptance "
            "under full GitHub catalog exposure versus the frozen one-tool treatment."
        ),
        authority_boundaries_sha256=(
            "dynamic-exposure-claim-boundary-v0:"
            "scientific-n=0;independent-validation=not-established;"
            "canonical-efficacy=not-established;high-assurance=not-authorized"
        ),
        control=PairedTaskArm(
            catalog_sha256=tool_catalog_snapshot_sha256(control),
            model_visible_exposure_observed=False,
        ),
        treatment=PairedTaskArm(
            catalog_sha256=tool_catalog_snapshot_sha256(treatment),
            model_visible_exposure_observed=False,
        ),
    )

    actual = evaluation.evaluate()
    expected = json.loads(RESULT.read_text(encoding="utf-8"))

    for key, value in actual.items():
        assert expected[key] == value

    assert expected["status"] == PAIRED_BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED
    assert expected["control_model_visible_tool_tokens"] is None
    assert expected["treatment_model_visible_tool_tokens"] is None
    assert expected["selected_tool"] is None
    assert expected["scientific_n_increment"] == 0
    assert expected["efficacy_effect"] == "NONE"
