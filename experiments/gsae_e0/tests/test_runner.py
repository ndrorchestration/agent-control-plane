from pathlib import Path

import pytest

from experiments.gsae_e0.runner import (
    SourceBindingError,
    observe_native_fixture,
    verify_source_binding,
)
from experiments.gsae_e0.schema import FixtureDisposition


SOURCE_SHA = "07a09698ca66e8837d04e6ec05b4de3448eced04"


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
