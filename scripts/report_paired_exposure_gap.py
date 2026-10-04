#!/usr/bin/env python3
"""Report CEP paired end-to-end eligibility without inventing runtime observations."""

from __future__ import annotations

import json
from pathlib import Path

from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
    tool_catalog_snapshot_sha256,
)
from agent_control_plane.context_paired_evaluation import (
    PairedTaskArm,
    PairedTaskEvaluation,
)


CONTROL = Path(
    "experiments/context_efficiency/catalogs/github-connector-runtime-2026-10-04.json"
)
TREATMENT = Path(
    "experiments/context_efficiency/catalogs/github-status-treatment-2026-10-04.json"
)


def load(path: Path):
    return tool_catalog_snapshot_from_mapping(
        json.loads(path.read_text(encoding="utf-8"))
    )


def main() -> int:
    control = load(CONTROL)
    treatment = load(TREATMENT)

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

    result = evaluation.evaluate()
    result["claim_boundary"] = (
        "Catalog identities are frozen, but neither arm has direct evidence of "
        "model-visible dynamic exposure or paired live-task execution."
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
