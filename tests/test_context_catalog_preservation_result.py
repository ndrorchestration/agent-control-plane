import json
from pathlib import Path

from agent_control_plane.context_baseline import BaselineObservation
from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
    tool_catalog_snapshot_sha256,
)
from agent_control_plane.context_comparison import (
    ComparisonPlan,
    TreatmentObservation,
    evaluate_treatment,
)
from agent_control_plane.context_metrics import ContextTelemetry
from agent_control_plane.context_state import ContextState, EvidenceReference
from agent_control_plane.context_tool_exposure import gate_by_required_capabilities


SNAPSHOT = Path(
    "experiments/context_efficiency/catalogs/github-connector-runtime-2026-10-04.json"
)
RESULT = Path(
    "experiments/context_efficiency/results/github-connector-runtime-preservation-2026-10-04.json"
)
SNAPSHOT_SHA = "f9d463a1c8519061087cba30bd648b68357949f20ce932c61c3f99821663b82e"
REQUIRED_TOOL = "mcp__GitHub__fetch_commit_workflow_runs"


def frozen_context_state() -> ContextState:
    return ContextState(
        task_id="github-exact-head-status-catalog-preservation-001",
        objective=(
            "Preserve the exact workflow-runs capability for an exact-head status "
            "lookup while reducing exposed GitHub connector descriptors."
        ),
        authority_boundaries=(
            "SCIENTIFIC_N_INCREMENT=0",
            "INDEPENDENT_VALIDATION=NOT_ESTABLISHED",
            "CANONICAL_DGAF_EFFICACY=NOT_ESTABLISHED",
            "HIGH_ASSURANCE=NOT_AUTHORIZED",
            "AUTOMATIC_CONTEXT_GATING=NOT_ENABLED",
        ),
        evidence=(
            EvidenceReference(
                source="chatgpt-runtime://GitHub/connector-catalog",
                identity=SNAPSHOT_SHA,
                locator=(
                    "experiments/context_efficiency/catalogs/"
                    "github-connector-runtime-2026-10-04.json"
                ),
            ),
            EvidenceReference(
                source="github-actions://ndrorchestration/agent-control-plane",
                identity="37190030512",
                locator="cep-baseline-001 observed workflow-runs lookup",
            ),
        ),
        unresolved=(
            "This structural comparison does not execute a live model task under "
            "gated exposure.",
        ),
        recent_delta=(
            "Frozen catalog contains 89 GitHub connector descriptors and the "
            "required workflow-runs descriptor.",
        ),
        next_action=(
            "Evaluate static descriptor-preservation and context-cost reduction only."
        ),
    )


def test_frozen_real_catalog_preservation_result_is_reproducible() -> None:
    snapshot = tool_catalog_snapshot_from_mapping(
        json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    )
    assert tool_catalog_snapshot_sha256(snapshot) == SNAPSHOT_SHA

    gated = gate_by_required_capabilities(
        snapshot.descriptors,
        required_capabilities=frozenset({"github.status.commit_workflow_runs"}),
    )
    assert [tool.name for tool in gated] == [REQUIRED_TOOL]

    task_contract = (
        "From the frozen 89-descriptor GitHub connector snapshot, preserve "
        "mcp__GitHub__fetch_commit_workflow_runs for an exact-head status lookup "
        "while reducing descriptor exposure; do not execute tools."
    )
    state = frozen_context_state()
    baseline = BaselineObservation(
        observation_id="github-connector-runtime-control-001",
        task_contract=task_contract,
        context_state=state,
        telemetry=ContextTelemetry(
            tool_definitions_exposed=len(snapshot.descriptors),
            tools_invoked=0,
        ),
        outcome="required_tool_available",
        acceptance="accepted",
        notes=(
            "Structural control over the frozen real GitHub connector metadata "
            "snapshot; no live model/tool execution."
        ),
    )
    plan = ComparisonPlan(
        plan_id="github-connector-runtime-preservation-001",
        baseline=baseline,
        treatment="exact-capability descriptor gating",
        primary_metric="tool_definitions_exposed",
        preservation_checks=(
            "same task contract",
            "same authority boundaries",
            "same canonical evidence references",
            "required operational tool remains available",
            "no acceptance regression",
        ),
        acceptance_rule=(
            "reduce descriptor exposure while preserving the required operational tool "
            "and all bounded preservation checks"
        ),
    )
    treatment = TreatmentObservation(
        task_contract=task_contract,
        context_state=state,
        telemetry=ContextTelemetry(
            tool_definitions_exposed=len(gated),
            tools_invoked=0,
        ),
        outcome="required_tool_available",
        acceptance="accepted",
    )
    comparison = evaluate_treatment(plan, treatment)

    actual = {
        "schema": "agent-control-plane.context-catalog-preservation-result.v0-candidate",
        "snapshot_sha256": SNAPSHOT_SHA,
        "required_tool": REQUIRED_TOOL,
        "control_descriptor_count": len(snapshot.descriptors),
        "treatment_descriptor_count": len(gated),
        "comparison": comparison.to_mapping(),
        "claim_boundary": (
            "Structural frozen-catalog preservation only; no live model task, "
            "latency/cost result, task efficacy, independent validation, execution "
            "authority, or High-Assurance."
        ),
    }
    expected = json.loads(RESULT.read_text(encoding="utf-8"))

    assert actual == expected
