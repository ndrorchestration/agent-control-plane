from dataclasses import replace

import pytest

from experiments.gsae_e0.manifest import (
    EvidenceBundle,
    EvidenceValidationError,
    canonical_bundle_sha256,
    result_id,
    validate_evidence_bundle,
)
from experiments.gsae_e0.schema import (
    AggregateDisposition,
    FixtureDisposition,
    FixtureResult,
)


SOURCE_SHA = "07a09698ca66e8837d04e6ec05b4de3448eced04"
SCHEMA_VERSION = "agent-control-plane.execution.v1"
FIXTURE_HASH = "79eda76151d82f9e0292e441bc6f7fe6572d858930baaaf8ddb0560641643bd6"
HARNESS_SHA = "8" * 40


def fixture_result(
    fixture_id="AUTH-02",
    *,
    run_id="run-1",
    attempt=1,
    prior_result_id=None,
):
    return FixtureResult(
        result_id=result_id(run_id, fixture_id, attempt),
        run_id=run_id,
        attempt=attempt,
        fixture_id=fixture_id,
        disposition=FixtureDisposition.STRUCTURED_COVERAGE,
        source_under_test_sha=SOURCE_SHA,
        schema_version=SCHEMA_VERSION,
        fixture_manifest_sha256=FIXTURE_HASH,
        structured_fields_used=("capability",),
        evidence_summary="synthetic apparatus evidence",
        prior_result_id=prior_result_id,
    )


def bundle(results=None):
    if results is None:
        results = (fixture_result(),)
    return EvidenceBundle(
        experiment_id="GSAE-E0",
        protocol_version="GSAE-E0-R2-v0.1",
        run_id="run-1",
        authorization_record_id="synthetic-authorization-record",
        source_under_test_sha=SOURCE_SHA,
        harness_commit_sha=HARNESS_SHA,
        schema_version=SCHEMA_VERSION,
        fixture_set_version="stage-a-v1",
        fixture_manifest_sha256=FIXTURE_HASH,
        results=tuple(results),
        aggregate_disposition=AggregateDisposition.FEASIBLE,
        test_command="python -m pytest",
        test_summary="synthetic apparatus verification",
        evidence_ceiling="contract-feasibility evidence only",
    )


def test_result_id_is_deterministic_per_attempt_and_changes_on_retry():
    first = result_id("run-1", "AUTH-01", 1)
    same = result_id("run-1", "AUTH-01", 1)
    retry = result_id("run-1", "AUTH-01", 2)
    assert first == same
    assert first != retry


def test_semantically_identical_bundle_hash_is_stable():
    evidence = bundle()
    assert canonical_bundle_sha256(evidence) == canonical_bundle_sha256(evidence)
    assert len(canonical_bundle_sha256(evidence)) == 64


def test_valid_bundle_passes_validation():
    evidence = bundle()
    validate_evidence_bundle(evidence, known_fixture_ids={"AUTH-02"})


def test_blank_result_id_is_rejected():
    broken = replace(fixture_result(), result_id="")
    with pytest.raises((EvidenceValidationError, ValueError), match="result_id"):
        validate_evidence_bundle(bundle((broken,)), known_fixture_ids={"AUTH-02"})


def test_duplicate_result_ids_are_rejected():
    first = fixture_result("AUTH-02")
    second = replace(fixture_result("AUTH-03"), result_id=first.result_id)
    with pytest.raises(EvidenceValidationError, match="duplicate result_id"):
        validate_evidence_bundle(bundle((first, second)), known_fixture_ids={"AUTH-02", "AUTH-03"})


def test_unknown_fixture_id_is_rejected():
    with pytest.raises(EvidenceValidationError, match="unknown fixture_id"):
        validate_evidence_bundle(bundle(), known_fixture_ids={"AUTH-01"})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_under_test_sha", "0" * 40, "source_under_test_sha"),
        ("schema_version", "wrong-schema", "schema_version"),
        ("fixture_manifest_sha256", "b" * 64, "fixture_manifest_sha256"),
    ],
)
def test_result_binding_mismatch_is_rejected(field, value, message):
    broken = replace(fixture_result(), **{field: value})
    with pytest.raises(EvidenceValidationError, match=message):
        validate_evidence_bundle(bundle((broken,)), known_fixture_ids={"AUTH-02"})


def test_retry_must_point_to_exact_prior_attempt_result():
    first = fixture_result("AUTH-02", attempt=1)
    retry = fixture_result(
        "AUTH-02",
        attempt=2,
        prior_result_id="not-the-prior-result",
    )
    with pytest.raises(EvidenceValidationError, match="prior_result_id"):
        validate_evidence_bundle(bundle((first, retry)), known_fixture_ids={"AUTH-02"})


def test_retry_chain_with_exact_prior_result_is_valid():
    first = fixture_result("AUTH-02", attempt=1)
    retry = fixture_result(
        "AUTH-02",
        attempt=2,
        prior_result_id=first.result_id,
    )
    evidence = bundle((first, retry))
    validate_evidence_bundle(evidence, known_fixture_ids={"AUTH-02"})
