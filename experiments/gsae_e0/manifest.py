"""Deterministic evidence bundle construction for GSAE-E0 Stage A."""

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Iterable
from uuid import UUID, uuid5

from .schema import AggregateDisposition, FixtureResult


_RESULT_NAMESPACE = UUID("e063a317-67cb-5d84-a411-7027376c68a0")


class EvidenceValidationError(ValueError):
    """Raised when an evidence bundle is incomplete or internally inconsistent."""


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{field_name} must be a non-blank string")
    return value.strip()


def _sha(value: object, field_name: str, length: int) -> str:
    text = _required_text(value, field_name)
    if re.fullmatch(rf"[0-9a-f]{{{length}}}", text) is None:
        raise EvidenceValidationError(
            f"{field_name} must be {length} lowercase hexadecimal characters"
        )
    return text


def result_id(run_id: str, fixture_id: str, attempt: int) -> str:
    """Derive a deterministic result identity while making retries distinct."""
    run = _required_text(run_id, "run_id")
    fixture = _required_text(fixture_id, "fixture_id")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise EvidenceValidationError("attempt must be an integer >= 1")
    return str(uuid5(_RESULT_NAMESPACE, f"{run}|{fixture}|{attempt}"))


@dataclass(frozen=True)
class EvidenceBundle:
    experiment_id: str
    protocol_version: str
    run_id: str
    authorization_record_id: str
    source_under_test_sha: str
    harness_commit_sha: str
    schema_version: str
    fixture_set_version: str
    fixture_manifest_sha256: str
    results: tuple[FixtureResult, ...]
    aggregate_disposition: AggregateDisposition
    test_command: str
    test_summary: str
    evidence_ceiling: str

    def to_dict(self) -> dict[str, object]:
        """Return the semantic, hash-bearing representation with stable ordering inputs."""
        return {
            "experiment_id": self.experiment_id,
            "protocol_version": self.protocol_version,
            "run_id": self.run_id,
            "authorization_record_id": self.authorization_record_id,
            "source_under_test_sha": self.source_under_test_sha,
            "harness_commit_sha": self.harness_commit_sha,
            "schema_version": self.schema_version,
            "fixture_set_version": self.fixture_set_version,
            "fixture_manifest_sha256": self.fixture_manifest_sha256,
            "results": [_result_to_dict(result) for result in self.results],
            "aggregate_disposition": self.aggregate_disposition.value,
            "test_command": self.test_command,
            "test_summary": self.test_summary,
            "evidence_ceiling": self.evidence_ceiling,
        }


def _result_to_dict(result: FixtureResult) -> dict[str, object]:
    data = asdict(result)
    data["disposition"] = result.disposition.value
    data["exception_class"] = (
        result.exception_class.value if result.exception_class is not None else None
    )
    data["structured_fields_used"] = list(result.structured_fields_used)
    return data


def canonical_bundle_bytes(bundle: EvidenceBundle) -> bytes:
    """Serialize the semantic evidence body deterministically."""
    return (
        json.dumps(
            bundle.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_bundle_sha256(bundle: EvidenceBundle) -> str:
    return hashlib.sha256(canonical_bundle_bytes(bundle)).hexdigest()


def build_evidence_bundle(
    *,
    experiment_id: str,
    protocol_version: str,
    run_id: str,
    authorization_record_id: str,
    source_under_test_sha: str,
    harness_commit_sha: str,
    schema_version: str,
    fixture_set_version: str,
    fixture_manifest_sha256: str,
    results: Iterable[FixtureResult],
    aggregate_disposition: AggregateDisposition,
    test_command: str,
    test_summary: str,
    evidence_ceiling: str,
    known_fixture_ids: set[str] | frozenset[str],
) -> EvidenceBundle:
    """Construct and validate one in-memory Stage-A evidence bundle."""
    bundle = EvidenceBundle(
        experiment_id=experiment_id,
        protocol_version=protocol_version,
        run_id=run_id,
        authorization_record_id=authorization_record_id,
        source_under_test_sha=source_under_test_sha,
        harness_commit_sha=harness_commit_sha,
        schema_version=schema_version,
        fixture_set_version=fixture_set_version,
        fixture_manifest_sha256=fixture_manifest_sha256,
        results=tuple(results),
        aggregate_disposition=aggregate_disposition,
        test_command=test_command,
        test_summary=test_summary,
        evidence_ceiling=evidence_ceiling,
    )
    validate_evidence_bundle(bundle, known_fixture_ids=known_fixture_ids)
    return bundle


def validate_evidence_bundle(
    bundle: EvidenceBundle,
    *,
    known_fixture_ids: set[str] | frozenset[str],
) -> None:
    """Fail closed on missing identities, binding drift, and invalid retry history."""
    if not isinstance(bundle, EvidenceBundle):
        raise EvidenceValidationError("bundle must be EvidenceBundle")

    _required_text(bundle.experiment_id, "experiment_id")
    _required_text(bundle.protocol_version, "protocol_version")
    _required_text(bundle.run_id, "run_id")
    _required_text(bundle.authorization_record_id, "authorization_record_id")
    _sha(bundle.source_under_test_sha, "source_under_test_sha", 40)
    _sha(bundle.harness_commit_sha, "harness_commit_sha", 40)
    _required_text(bundle.schema_version, "schema_version")
    _required_text(bundle.fixture_set_version, "fixture_set_version")
    _sha(bundle.fixture_manifest_sha256, "fixture_manifest_sha256", 64)
    _required_text(bundle.test_command, "test_command")
    _required_text(bundle.test_summary, "test_summary")
    _required_text(bundle.evidence_ceiling, "evidence_ceiling")
    if not isinstance(bundle.aggregate_disposition, AggregateDisposition):
        raise EvidenceValidationError("aggregate_disposition must be AggregateDisposition")
    if not bundle.results:
        raise EvidenceValidationError("results must not be empty")

    known = set(known_fixture_ids)
    if not known or any(not isinstance(item, str) or not item.strip() for item in known):
        raise EvidenceValidationError("known_fixture_ids must contain non-blank strings")

    result_ids: set[str] = set()
    attempts: dict[tuple[str, int], FixtureResult] = {}

    for result in bundle.results:
        result_identity = _required_text(result.result_id, "result_id")
        if result_identity in result_ids:
            raise EvidenceValidationError("duplicate result_id")
        result_ids.add(result_identity)

        if result.fixture_id not in known:
            raise EvidenceValidationError(f"unknown fixture_id: {result.fixture_id}")
        if result.run_id != bundle.run_id:
            raise EvidenceValidationError("result run_id does not match bundle run_id")
        if result.source_under_test_sha != bundle.source_under_test_sha:
            raise EvidenceValidationError("result source_under_test_sha does not match bundle")
        if result.schema_version != bundle.schema_version:
            raise EvidenceValidationError("result schema_version does not match bundle")
        if result.fixture_manifest_sha256 != bundle.fixture_manifest_sha256:
            raise EvidenceValidationError("result fixture_manifest_sha256 does not match bundle")

        expected_id = result_id(result.run_id, result.fixture_id, result.attempt)
        if result.result_id != expected_id:
            raise EvidenceValidationError("result_id does not match deterministic identity")

        key = (result.fixture_id, result.attempt)
        if key in attempts:
            raise EvidenceValidationError("duplicate fixture attempt")
        attempts[key] = result

    for (fixture_id, attempt), result in attempts.items():
        if attempt == 1:
            if result.prior_result_id is not None:
                raise EvidenceValidationError("attempt 1 must not set prior_result_id")
            continue

        prior = attempts.get((fixture_id, attempt - 1))
        if prior is None:
            raise EvidenceValidationError("retry is missing the immediately prior attempt")
        if result.prior_result_id != prior.result_id:
            raise EvidenceValidationError("prior_result_id does not match prior attempt")
