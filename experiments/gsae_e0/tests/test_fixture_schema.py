from pathlib import Path

import pytest

from experiments.gsae_e0.fixtures import fixture_manifest_sha256, load_fixture_manifest
from experiments.gsae_e0.schema import FixtureManifest, FixtureValidationError


FIXTURE_PATH = Path("experiments/gsae_e0/fixtures/stage_a_v1.json")


def valid_fixture(fixture_id="AUTH-01"):
    return {
        "fixture_id": fixture_id,
        "family": "authority_semantic",
        "title": "principal identity",
        "purpose": "require structured principal identity",
        "criticality": "critical",
        "required_semantics": ["principal_identity"],
        "input_spec": {
            "required_path_groups": [["principal.principal_id"]],
            "gap_class_if_absent": "MISSING_CORE_SEMANTIC",
        },
        "expected_classification_domain": ["STRUCTURED_COVERAGE", "NOT_COVERED"],
    }


def valid_manifest():
    return {
        "experiment_id": "GSAE-E0",
        "fixture_set_version": "stage-a-v1",
        "source_under_test_sha": "07a09698ca66e8837d04e6ec05b4de3448eced04",
        "schema_version": "agent-control-plane.execution.v1",
        "fixtures": [valid_fixture()],
    }


def test_valid_manifest_parses():
    manifest = FixtureManifest.from_dict(valid_manifest())
    assert manifest.experiment_id == "GSAE-E0"
    assert manifest.fixtures[0].fixture_id == "AUTH-01"


def test_duplicate_fixture_ids_fail_closed():
    data = valid_manifest()
    data["fixtures"] = [valid_fixture("AUTH-01"), valid_fixture("AUTH-01")]
    with pytest.raises(FixtureValidationError, match="duplicate fixture_id"):
        FixtureManifest.from_dict(data)


def test_blank_fixture_id_fails_closed():
    data = valid_manifest()
    data["fixtures"] = [valid_fixture("   ")]
    with pytest.raises(FixtureValidationError, match="fixture_id"):
        FixtureManifest.from_dict(data)


def test_unknown_gap_class_fails_closed():
    data = valid_manifest()
    data["fixtures"][0]["input_spec"]["gap_class_if_absent"] = "MYSTERY"
    with pytest.raises(FixtureValidationError, match="gap_class_if_absent"):
        FixtureManifest.from_dict(data)


def test_empty_required_semantics_fail_closed():
    data = valid_manifest()
    data["fixtures"][0]["required_semantics"] = []
    with pytest.raises(FixtureValidationError, match="required_semantics"):
        FixtureManifest.from_dict(data)


def test_malformed_required_path_groups_fail_closed():
    data = valid_manifest()
    data["fixtures"][0]["input_spec"]["required_path_groups"] = [[]]
    with pytest.raises(FixtureValidationError, match="required_path_groups"):
        FixtureManifest.from_dict(data)


def test_frozen_stage_a_fixture_ids_are_exact():
    manifest = load_fixture_manifest(FIXTURE_PATH)
    assert {fixture.fixture_id for fixture in manifest.fixtures} == {
        "NATIVE-01",
        "NATIVE-02",
        "NATIVE-03",
        "NATIVE-04",
        "NATIVE-05",
        "NATIVE-06",
        "NATIVE-07",
        "NATIVE-08",
        "NATIVE-09",
        "NATIVE-10",
        "NEG-01",
        "NEG-02",
        "NEG-03",
        "NEG-04",
        "NEG-05",
        "NEG-06",
        "NEG-07",
        "NEG-08",
        "AUTH-01",
        "AUTH-02",
        "AUTH-03",
        "AUTH-04",
        "AUTH-05",
        "AUTH-06",
        "AUTH-07",
        "AUTH-08",
        "AUTH-09",
        "AUTH-10",
    }


def test_fixture_hash_is_64_lower_hex_and_stable():
    first = fixture_manifest_sha256(FIXTURE_PATH)
    second = fixture_manifest_sha256(FIXTURE_PATH)
    assert first == second
    assert len(first) == 64
    assert first == first.lower()
