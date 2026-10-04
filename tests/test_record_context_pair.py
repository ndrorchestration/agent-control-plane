import json
from pathlib import Path
import runpy

import pytest

from agent_control_plane.context_baseline import (
    BaselineObservation,
    baseline_observation_envelope,
)
from agent_control_plane.context_metrics import ContextTelemetry
from agent_control_plane.context_state import (
    ContextState,
    EvidenceReference,
    context_state_to_mapping,
)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_context_pair.py"
module = runpy.run_path(str(SCRIPT))
load_observation = module["_load_observation"]


def state() -> ContextState:
    return ContextState(
        task_id="task-1",
        objective="inspect exact-head workflow status",
        authority_boundaries=("AUTOMATIC_CONTEXT_GATING=NOT_ENABLED",),
        evidence=(
            EvidenceReference(
                source="github://example/repo",
                identity="abc123",
            ),
        ),
    )


def write_observation(tmp_path: Path, *, tamper: bool = False) -> tuple[Path, Path]:
    context = state()
    observation = BaselineObservation(
        observation_id="obs-1",
        task_contract="report exact-head workflow status",
        context_state=context,
        telemetry=ContextTelemetry(input_tokens=100, tool_definitions_exposed=89),
        outcome="completed",
        acceptance="accepted",
    )
    state_path = tmp_path / "state.json"
    observation_path = tmp_path / "observation.json"
    state_path.write_text(
        json.dumps(context_state_to_mapping(context)),
        encoding="utf-8",
    )
    envelope = baseline_observation_envelope(observation)
    if tamper:
        envelope["observation_sha256"] = "0" * 64
    observation_path.write_text(json.dumps(envelope), encoding="utf-8")
    return observation_path, state_path


def test_loader_accepts_identity_bound_external_observation(tmp_path: Path) -> None:
    observation_path, state_path = write_observation(tmp_path)

    loaded = load_observation(observation_path, state_path)

    assert loaded.observation_id == "obs-1"
    assert loaded.telemetry.input_tokens == 100


def test_loader_rejects_tampered_observation_identity(tmp_path: Path) -> None:
    observation_path, state_path = write_observation(tmp_path, tamper=True)

    with pytest.raises(ValueError, match="identity mismatch"):
        load_observation(observation_path, state_path)
