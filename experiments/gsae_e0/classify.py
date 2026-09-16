"""Pure structured-coverage and aggregate classification for GSAE-E0 Stage A."""

from dataclasses import fields
from typing import Iterable

from agent_control_plane.contract import (
    ArtifactRef,
    ComponentIdentity,
    ExecutionEvent,
    ExecutionIdentity,
    TraceContext,
)

from .schema import (
    AggregateDisposition,
    Criticality,
    ExceptionClass,
    FixtureDefinition,
    FixtureDisposition,
    FixtureFamily,
    FixtureResult,
)


_AUTHORITY_ESCAPE_HATCH_PATHS = frozenset(
    {
        "detail",
        "input_artifacts[].uri",
        "output_artifacts[].uri",
    }
)

_NOT_FEASIBLE_GAP_CLASSES = frozenset(
    {
        ExceptionClass.MISSING_CORE_SEMANTIC,
        ExceptionClass.AMBIGUOUS_SEMANTIC,
        ExceptionClass.RUNTIME_SPECIFIC,
        ExceptionClass.ADAPTER_COMPLEXITY,
    }
)


def _paths_for(dataclass_type: type, prefix: str = "") -> set[str]:
    return {f"{prefix}{field.name}" for field in fields(dataclass_type)}


def execution_v1_surface_paths() -> frozenset[str]:
    """Return only machine-addressable fields actually present in execution.v1.

    This deliberately does not create conceptual aliases for meanings that the
    contract does not structurally encode.
    """
    paths = _paths_for(ExecutionEvent)
    paths.update(_paths_for(ExecutionIdentity, "identity."))
    paths.update(_paths_for(TraceContext, "trace."))
    paths.update(_paths_for(ComponentIdentity, "component."))
    paths.update(_paths_for(ArtifactRef, "input_artifacts[]."))
    paths.update(_paths_for(ArtifactRef, "output_artifacts[]."))
    return frozenset(paths)


def classify_authority_fixture(
    fixture: FixtureDefinition,
    surface_paths: frozenset[str],
    *,
    result_id: str,
    run_id: str,
    attempt: int,
    source_under_test_sha: str,
    schema_version: str,
    fixture_manifest_sha256: str,
    prior_result_id: str | None = None,
) -> FixtureResult:
    """Classify one authority-semantic fixture against a typed field surface."""
    if fixture.family is not FixtureFamily.AUTHORITY:
        raise ValueError("classify_authority_fixture requires an authority_semantic fixture")

    groups = fixture.input_spec.get("required_path_groups")
    if not isinstance(groups, tuple) or not groups:
        raise ValueError("authority fixture lacks validated required_path_groups")

    matched: list[str] = []
    for group in groups:
        eligible = sorted(
            path
            for path in group
            if path in surface_paths and path not in _AUTHORITY_ESCAPE_HATCH_PATHS
        )
        if not eligible:
            gap_class = ExceptionClass(fixture.input_spec["gap_class_if_absent"])
            return FixtureResult(
                result_id=result_id,
                run_id=run_id,
                attempt=attempt,
                fixture_id=fixture.fixture_id,
                disposition=FixtureDisposition.NOT_COVERED,
                source_under_test_sha=source_under_test_sha,
                schema_version=schema_version,
                fixture_manifest_sha256=fixture_manifest_sha256,
                structured_fields_used=(),
                exception_class=gap_class,
                evidence_summary="one or more required structured path groups are absent",
                prior_result_id=prior_result_id,
            )
        matched.append(eligible[0])

    return FixtureResult(
        result_id=result_id,
        run_id=run_id,
        attempt=attempt,
        fixture_id=fixture.fixture_id,
        disposition=FixtureDisposition.STRUCTURED_COVERAGE,
        source_under_test_sha=source_under_test_sha,
        schema_version=schema_version,
        fixture_manifest_sha256=fixture_manifest_sha256,
        structured_fields_used=tuple(matched),
        evidence_summary="all required structured path groups are represented",
        prior_result_id=prior_result_id,
    )


def aggregate_disposition(
    fixtures: Iterable[FixtureDefinition],
    results: Iterable[FixtureResult],
) -> AggregateDisposition:
    """Derive the bounded Stage-A disposition with fail-closed precedence."""
    fixture_tuple = tuple(fixtures)
    result_tuple = tuple(results)

    fixture_ids = [fixture.fixture_id for fixture in fixture_tuple]
    result_ids = [result.fixture_id for result in result_tuple]

    if not fixture_tuple:
        return AggregateDisposition.NOT_ESTABLISHED
    if len(fixture_ids) != len(set(fixture_ids)):
        return AggregateDisposition.NOT_ESTABLISHED
    if len(result_ids) != len(set(result_ids)):
        return AggregateDisposition.NOT_ESTABLISHED
    if set(result_ids) != set(fixture_ids):
        return AggregateDisposition.NOT_ESTABLISHED

    by_fixture = {result.fixture_id: result for result in result_tuple}

    for fixture in fixture_tuple:
        result = by_fixture[fixture.fixture_id]
        if result.disposition not in fixture.expected_classification_domain:
            return AggregateDisposition.NOT_ESTABLISHED
        if result.disposition is FixtureDisposition.NOT_ESTABLISHED:
            return AggregateDisposition.NOT_ESTABLISHED
        if result.exception_class in {
            ExceptionClass.PROVENANCE_GAP,
            ExceptionClass.IMPLEMENTATION_DEFECT,
        }:
            return AggregateDisposition.NOT_ESTABLISHED

    for fixture in fixture_tuple:
        result = by_fixture[fixture.fixture_id]
        if (
            fixture.criticality is Criticality.CRITICAL
            and result.disposition is FixtureDisposition.NOT_COVERED
            and result.exception_class in _NOT_FEASIBLE_GAP_CLASSES
        ):
            return AggregateDisposition.NOT_FEASIBLE
        if fixture.criticality is Criticality.CRITICAL and result.disposition is FixtureDisposition.NOT_COVERED:
            return AggregateDisposition.NOT_ESTABLISHED

    if any(
        fixture.criticality is Criticality.NONCRITICAL
        and by_fixture[fixture.fixture_id].disposition is FixtureDisposition.NOT_COVERED
        for fixture in fixture_tuple
    ):
        return AggregateDisposition.CONDITIONAL

    return AggregateDisposition.FEASIBLE
