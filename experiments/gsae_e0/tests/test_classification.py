from experiments.gsae_e0.classify import (
    aggregate_disposition,
    classify_authority_fixture,
    execution_v1_surface_paths,
)
from experiments.gsae_e0.schema import (
    AggregateDisposition,
    Criticality,
    ExceptionClass,
    FixtureDefinition,
    FixtureDisposition,
    FixtureFamily,
    FixtureResult,
)


SOURCE_SHA = "07a09698ca66e8837d04e6ec05b4de3448eced04"
SCHEMA_VERSION = "agent-control-plane.execution.v1"
FIXTURE_HASH = "a" * 64


def authority_fixture(
    fixture_id="AUTH-01",
    groups=None,
    gap_class="MISSING_CORE_SEMANTIC",
    criticality="critical",
):
    if groups is None:
        groups = [["principal.principal_id"]]
    return FixtureDefinition.from_dict(
        {
            "fixture_id": fixture_id,
            "family": "authority_semantic",
            "title": fixture_id,
            "purpose": "synthetic apparatus classification test",
            "criticality": criticality,
            "required_semantics": ["synthetic_semantic"],
            "input_spec": {
                "required_path_groups": groups,
                "gap_class_if_absent": gap_class,
            },
            "expected_classification_domain": ["STRUCTURED_COVERAGE", "NOT_COVERED"],
        }
    )


def result_context(result_id="result-1"):
    return {
        "result_id": result_id,
        "run_id": "synthetic-run",
        "attempt": 1,
        "source_under_test_sha": SOURCE_SHA,
        "schema_version": SCHEMA_VERSION,
        "fixture_manifest_sha256": FIXTURE_HASH,
    }


def result_for(
    fixture_id,
    disposition,
    *,
    exception_class=None,
    result_id=None,
):
    return FixtureResult(
        result_id=result_id or f"result-{fixture_id}",
        run_id="synthetic-run",
        attempt=1,
        fixture_id=fixture_id,
        disposition=disposition,
        source_under_test_sha=SOURCE_SHA,
        schema_version=SCHEMA_VERSION,
        fixture_manifest_sha256=FIXTURE_HASH,
        exception_class=exception_class,
    )


def test_execution_v1_surface_contains_only_actual_structured_contract_paths():
    surface = execution_v1_surface_paths()
    assert "capability" in surface
    assert "policy_decision_ref" in surface
    assert "identity.run_id" in surface
    assert "trace.parent_span_id" in surface
    assert "component.adapter_id" in surface
    assert "input_artifacts[].sha256" in surface
    assert "output_artifacts[].artifact_id" in surface
    assert "principal.principal_id" not in surface
    assert "resource.resource_id" not in surface
    assert "policy.version_or_hash" not in surface
    assert "delegation.scope" not in surface


def test_detail_escape_hatch_does_not_count_as_structured_authority_coverage():
    fixture = authority_fixture(groups=[["principal.principal_id"]])
    result = classify_authority_fixture(
        fixture,
        frozenset({"detail"}),
        **result_context(),
    )
    assert result.disposition is FixtureDisposition.NOT_COVERED
    assert result.exception_class is ExceptionClass.MISSING_CORE_SEMANTIC
    assert result.structured_fields_used == ()


def test_all_required_path_groups_must_be_satisfied():
    fixture = authority_fixture(
        fixture_id="AUTH-06",
        groups=[["policy_decision_ref"], ["decision.outcome"]],
    )
    result = classify_authority_fixture(
        fixture,
        frozenset({"policy_decision_ref"}),
        **result_context(),
    )
    assert result.disposition is FixtureDisposition.NOT_COVERED
    assert result.exception_class is ExceptionClass.MISSING_CORE_SEMANTIC


def test_structured_coverage_records_exact_matching_paths():
    fixture = authority_fixture(
        fixture_id="AUTH-02",
        groups=[["capability"]],
    )
    result = classify_authority_fixture(
        fixture,
        frozenset({"capability", "detail"}),
        **result_context(),
    )
    assert result.disposition is FixtureDisposition.STRUCTURED_COVERAGE
    assert result.exception_class is None
    assert result.structured_fields_used == ("capability",)


def test_critical_missing_semantic_forces_not_feasible():
    fixture = authority_fixture()
    result = result_for(
        fixture.fixture_id,
        FixtureDisposition.NOT_COVERED,
        exception_class=ExceptionClass.MISSING_CORE_SEMANTIC,
    )
    assert aggregate_disposition((fixture,), (result,)) is AggregateDisposition.NOT_FEASIBLE


def test_critical_ambiguous_semantic_forces_not_feasible():
    fixture = authority_fixture(gap_class="AMBIGUOUS_SEMANTIC")
    result = result_for(
        fixture.fixture_id,
        FixtureDisposition.NOT_COVERED,
        exception_class=ExceptionClass.AMBIGUOUS_SEMANTIC,
    )
    assert aggregate_disposition((fixture,), (result,)) is AggregateDisposition.NOT_FEASIBLE


def test_missing_result_for_required_fixture_forces_not_established():
    fixture = authority_fixture()
    assert aggregate_disposition((fixture,), ()) is AggregateDisposition.NOT_ESTABLISHED


def test_provenance_gap_forces_not_established():
    fixture = authority_fixture()
    result = result_for(
        fixture.fixture_id,
        FixtureDisposition.NOT_ESTABLISHED,
        exception_class=ExceptionClass.PROVENANCE_GAP,
    )
    assert aggregate_disposition((fixture,), (result,)) is AggregateDisposition.NOT_ESTABLISHED


def test_implementation_defect_forces_not_established():
    fixture = authority_fixture()
    result = result_for(
        fixture.fixture_id,
        FixtureDisposition.NOT_ESTABLISHED,
        exception_class=ExceptionClass.IMPLEMENTATION_DEFECT,
    )
    assert aggregate_disposition((fixture,), (result,)) is AggregateDisposition.NOT_ESTABLISHED


def test_noncritical_gap_with_all_critical_coverage_is_conditional():
    critical = authority_fixture(
        fixture_id="AUTH-C",
        groups=[["capability"]],
        criticality="critical",
    )
    noncritical = authority_fixture(
        fixture_id="AUTH-NC",
        groups=[["optional.extension"]],
        gap_class="NONCRITICAL_EXTENSION",
        criticality="noncritical",
    )
    critical_result = result_for(critical.fixture_id, FixtureDisposition.STRUCTURED_COVERAGE)
    noncritical_result = result_for(
        noncritical.fixture_id,
        FixtureDisposition.NOT_COVERED,
        exception_class=ExceptionClass.NONCRITICAL_EXTENSION,
    )
    assert (
        aggregate_disposition((critical, noncritical), (critical_result, noncritical_result))
        is AggregateDisposition.CONDITIONAL
    )


def test_all_required_results_satisfied_is_feasible_for_frozen_scope():
    fixture = authority_fixture(fixture_id="AUTH-02", groups=[["capability"]])
    result = result_for(fixture.fixture_id, FixtureDisposition.STRUCTURED_COVERAGE)
    assert aggregate_disposition((fixture,), (result,)) is AggregateDisposition.FEASIBLE


def test_unknown_result_fixture_id_fails_closed():
    fixture = authority_fixture()
    unknown = result_for("AUTH-UNKNOWN", FixtureDisposition.STRUCTURED_COVERAGE)
    assert aggregate_disposition((fixture,), (unknown,)) is AggregateDisposition.NOT_ESTABLISHED
