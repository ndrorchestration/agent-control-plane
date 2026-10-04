import pytest

from agent_control_plane.context_state import (
    CONTEXT_STATE_SCHEMA,
    ContextState,
    EvidenceReference,
    canonical_context_state_bytes,
    context_state_from_mapping,
    context_state_sha256,
    context_state_to_mapping,
)


def sample_state() -> ContextState:
    return ContextState(
        task_id="task-cep-001",
        objective="Measure baseline context construction without changing routing.",
        authority_boundaries=(
            "SCIENTIFIC_N_INCREMENT=0",
            "HIGH_ASSURANCE=NOT_AUTHORIZED",
        ),
        evidence=(
            EvidenceReference(
                source="github://ndrorchestration/agent-control-plane",
                identity="cad2ef94f1a690deee741b81ea8bfab8c248cd7d",
                locator="README.md",
            ),
        ),
        unresolved=("Establish token telemetry source.",),
        recent_delta=("CEP capability admitted in Notion.",),
        next_action="Collect baseline measurements.",
    )


def test_context_state_round_trip_is_strict_and_stable() -> None:
    state = sample_state()
    mapping = context_state_to_mapping(state)

    assert mapping["schema"] == CONTEXT_STATE_SCHEMA
    assert context_state_from_mapping(mapping) == state
    assert canonical_context_state_bytes(state) == canonical_context_state_bytes(state)
    assert len(context_state_sha256(state)) == 64


def test_evidence_reference_defaults_to_no_authority_effect() -> None:
    ref = EvidenceReference(source="notion://page", identity="abc123")
    assert ref.authority_effect == "NONE"


def test_context_state_rejects_unknown_fields() -> None:
    mapping = context_state_to_mapping(sample_state())
    mapping["unexpected"] = True

    with pytest.raises(ValueError, match="fields mismatch"):
        context_state_from_mapping(mapping)


def test_context_state_requires_explicit_evidence_shape() -> None:
    mapping = context_state_to_mapping(sample_state())
    mapping["evidence"][0].pop("authority_effect")

    with pytest.raises(ValueError, match="evidence reference fields mismatch"):
        context_state_from_mapping(mapping)


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", ""),
        ("objective", ""),
    ],
)
def test_context_state_rejects_empty_identity_fields(field: str, value: str) -> None:
    kwargs = {
        "task_id": "task-1",
        "objective": "objective",
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        ContextState(**kwargs)
