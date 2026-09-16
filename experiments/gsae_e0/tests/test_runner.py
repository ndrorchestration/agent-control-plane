import json
from pathlib import Path

import pytest

from experiments.gsae_e0.runner import (
    ExecutionGuardError,
    SourceBindingError,
    observe_native_fixture,
    run_stage_a,
    verify_source_binding,
)
from experiments.gsae_e0.schema import AggregateDisposition, FixtureDisposition


SOURCE_SHA = "07a09698ca66e8837d04e6ec05b4de3448eced04"
SCHEMA_VERSION = "agent-control-plane.execution.v1"


def test_bound_source_is_ancestor_and_acp_package_is_unchanged():
    verify_source_binding(Path.cwd(), SOURCE_SHA)


def test_unknown_source_sha_fails_closed():
    with pytest.raises(SourceBindingError):
        verify_source_binding(Path.cwd(), "0" * 40)


@pytest.mark.parametrize(
    ("fixture_id", "expected_disposition", "summary_fragment"),
    [
        ("NATIVE-01", FixtureDisposition.PASS, "task.completed"),
        ("NATIVE-02", FixtureDisposition.PASS, "task.denied"),
        ("NATIVE-03", FixtureDisposition.PASS, "task.rejected"),
        ("NATIVE-04", FixtureDisposition.PASS, "task.failed"),
        ("NATIVE-05", FixtureDisposition.PASS, "task.cancelled"),
        ("NATIVE-06", FixtureDisposition.PASS, "budget_exhausted"),
        ("NATIVE-07", FixtureDisposition.PASS, "artifact"),
        ("NATIVE-08", FixtureDisposition.PASS, "parent_span_id"),
        ("NATIVE-09", FixtureDisposition.PASS, "policy_decision_ref"),
        ("NATIVE-10", FixtureDisposition.PASS, "mapped provenance"),
        ("NEG-01", FixtureDisposition.EXPECTED_REJECTION, "run_id"),
        ("NEG-02", FixtureDisposition.EXPECTED_REJECTION, "schema_version"),
        ("NEG-03", FixtureDisposition.EXPECTED_REJECTION, "execution_id"),
        ("NEG-04", FixtureDisposition.EXPECTED_REJECTION, "parent_span_id"),
        ("NEG-05", FixtureDisposition.EXPECTED_REJECTION, "sha256"),
        ("NEG-06", FixtureDisposition.EXPECTED_REJECTION, "monotonic_ns"),
        ("NEG-07", FixtureDisposition.EXPECTED_REJECTION, "utc_timestamp"),
        ("NEG-08", FixtureDisposition.EXPECTED_REJECTION, "component"),
    ],
)
def test_native_observation_matches_expected_contract_behavior(
    fixture_id,
    expected_disposition,
    summary_fragment,
):
    disposition, summary = observe_native_fixture(fixture_id)
    assert disposition is expected_disposition
    assert summary_fragment in summary


def test_unknown_observation_fixture_fails_closed():
    with pytest.raises(ValueError, match="unknown native fixture"):
        observe_native_fixture("NATIVE-999")


def _synthetic_manifest(
    tmp_path: Path,
    *,
    experiment_id: str = "GSAE-E0",
    schema_version: str = SCHEMA_VERSION,
    source_sha: str = SOURCE_SHA,
) -> Path:
    path = tmp_path / "synthetic-fixture-manifest.json"
    path.write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "fixture_set_version": "synthetic-stage-a-v1",
                "source_under_test_sha": source_sha,
                "schema_version": schema_version,
                "fixtures": [
                    {
                        "fixture_id": "AUTH-SYNTHETIC-CAPABILITY",
                        "family": "authority_semantic",
                        "title": "synthetic capability probe",
                        "purpose": "exercise apparatus orchestration without the canonical fixture set",
                        "criticality": "critical",
                        "required_semantics": ["requested_capability"],
                        "input_spec": {
                            "required_path_groups": [["capability"]],
                            "gap_class_if_absent": "MISSING_CORE_SEMANTIC",
                        },
                        "expected_classification_domain": [
                            "STRUCTURED_COVERAGE",
                            "NOT_COVERED",
                        ],
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _run_kwargs(tmp_path: Path, **overrides):
    fixture_path = overrides.get("fixture_path")
    if fixture_path is None:
        fixture_path = _synthetic_manifest(tmp_path)
    values = {
        "repo_root": Path.cwd(),
        "fixture_path": fixture_path,
        "protocol_version": "GSAE-E0-R2-v0.1-SYNTHETIC",
        "authorization_record_id": "synthetic-apparatus-test-authorization",
        "run_id": "synthetic-stage-a-run",
        "harness_commit_sha": "8" * 40,
        "test_command": "python -m pytest experiments/gsae_e0/tests/test_runner.py",
        "test_summary": "synthetic apparatus orchestration only",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization_record_id", ""),
        ("protocol_version", " "),
        ("run_id", ""),
        ("harness_commit_sha", ""),
        ("test_command", ""),
        ("test_summary", ""),
    ],
)
def test_run_rejects_blank_required_execution_identity(tmp_path, field, value):
    with pytest.raises(ExecutionGuardError, match=field):
        run_stage_a(**_run_kwargs(tmp_path, **{field: value}))


def test_run_rejects_wrong_experiment_id(tmp_path):
    fixture_path = _synthetic_manifest(tmp_path, experiment_id="NOT-GSAE-E0")
    with pytest.raises(ExecutionGuardError, match="GSAE-E0"):
        run_stage_a(**_run_kwargs(tmp_path, fixture_path=fixture_path))


def test_run_rejects_schema_mismatch(tmp_path):
    fixture_path = _synthetic_manifest(tmp_path, schema_version="wrong-schema")
    with pytest.raises(ExecutionGuardError, match="schema_version"):
        run_stage_a(**_run_kwargs(tmp_path, fixture_path=fixture_path))


def test_run_rejects_unbound_source(tmp_path):
    fixture_path = _synthetic_manifest(tmp_path, source_sha="0" * 40)
    with pytest.raises(ExecutionGuardError, match="source"):
        run_stage_a(**_run_kwargs(tmp_path, fixture_path=fixture_path))


def test_synthetic_runner_returns_in_memory_bounded_bundle(tmp_path):
    evidence = run_stage_a(**_run_kwargs(tmp_path))
    assert evidence.experiment_id == "GSAE-E0"
    assert evidence.fixture_set_version == "synthetic-stage-a-v1"
    assert evidence.aggregate_disposition is AggregateDisposition.FEASIBLE
    assert [result.fixture_id for result in evidence.results] == [
        "AUTH-SYNTHETIC-CAPABILITY"
    ]
    assert not list(tmp_path.glob("*result*.json"))
    assert not list(tmp_path.glob("*evidence*.json"))
