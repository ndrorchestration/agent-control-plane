from agent_control_plane.context_tool_exposure import (
    ToolDescriptor,
    expose_all,
    exposure_count,
    gate_by_required_capabilities,
)


def catalog() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor("github.workflow_runs", frozenset({"github.status"})),
        ToolDescriptor("github.read_file", frozenset({"github.read"})),
        ToolDescriptor("github.write_file", frozenset({"github.write"})),
        ToolDescriptor("notion.search", frozenset({"notion.read"})),
        ToolDescriptor("notion.update", frozenset({"notion.write"})),
        ToolDescriptor("rdc.read_file", frozenset({"local.read"})),
        ToolDescriptor("rdc.start_process", frozenset({"local.execute"})),
        ToolDescriptor("web.search", frozenset({"web.read"})),
    )


def test_baseline_exposes_complete_catalog() -> None:
    exposed = expose_all(catalog())
    assert exposure_count(exposed) == 8


def test_candidate_gate_selects_only_required_capability() -> None:
    selected = gate_by_required_capabilities(
        catalog(),
        required_capabilities=frozenset({"github.status"}),
    )

    assert [tool.name for tool in selected] == ["github.workflow_runs"]
    assert exposure_count(selected) == 1


def test_empty_requirement_exposes_nothing_not_everything() -> None:
    assert gate_by_required_capabilities(
        catalog(),
        required_capabilities=frozenset(),
    ) == ()


def test_capability_gate_has_no_execution_surface() -> None:
    selected = gate_by_required_capabilities(
        catalog(),
        required_capabilities=frozenset({"github.write"}),
    )
    assert selected[0].name == "github.write_file"
    assert not hasattr(selected[0], "invoke")
    assert not hasattr(selected[0], "authority")



def test_canonical_exposure_bytes_are_deterministic_and_smaller_when_gated() -> None:
    from agent_control_plane.context_tool_exposure import (
        byte_reduction_fraction,
        canonical_tool_catalog_bytes,
        exposure_bytes,
    )

    full = tuple(
        ToolDescriptor(
            tool.name,
            tool.capabilities,
            schema_text=f'{{"name":"{tool.name}","args":["example"]}}',
        )
        for tool in catalog()
    )
    gated = gate_by_required_capabilities(
        full,
        required_capabilities=frozenset({"github.status"}),
    )

    assert canonical_tool_catalog_bytes(full) == canonical_tool_catalog_bytes(full)
    assert exposure_bytes(gated) < exposure_bytes(full)

    reduction = byte_reduction_fraction(full, gated)
    assert reduction is not None
    assert 0 < reduction < 1
