"""Typed schema and fail-closed validation for GSAE-E0 Stage-A evidence."""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping


class FixtureValidationError(ValueError):
    """Raised when fixture or result evidence is malformed."""


class Criticality(str, Enum):
    CRITICAL = "critical"
    NONCRITICAL = "noncritical"


class FixtureFamily(str, Enum):
    NATIVE = "native_conformance"
    NEGATIVE = "negative_control"
    AUTHORITY = "authority_semantic"


class ExceptionClass(str, Enum):
    MISSING_CORE_SEMANTIC = "MISSING_CORE_SEMANTIC"
    AMBIGUOUS_SEMANTIC = "AMBIGUOUS_SEMANTIC"
    RUNTIME_SPECIFIC = "RUNTIME_SPECIFIC"
    ADAPTER_COMPLEXITY = "ADAPTER_COMPLEXITY"
    NONCRITICAL_EXTENSION = "NONCRITICAL_EXTENSION"
    MALFORMED_INPUT = "MALFORMED_INPUT"
    IMPLEMENTATION_DEFECT = "IMPLEMENTATION_DEFECT"
    PROVENANCE_GAP = "PROVENANCE_GAP"


class FixtureDisposition(str, Enum):
    PASS = "PASS"
    STRUCTURED_COVERAGE = "STRUCTURED_COVERAGE"
    EXPECTED_REJECTION = "EXPECTED_REJECTION"
    NOT_COVERED = "NOT_COVERED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


class AggregateDisposition(str, Enum):
    FEASIBLE = "FEASIBLE_FOR_FROZEN_SCOPE"
    CONDITIONAL = "CONDITIONALLY_FEASIBLE_NARROW"
    NOT_FEASIBLE = "NOT_FEASIBLE_FOR_FROZEN_SCOPE"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureValidationError(f"{field_name} must be a non-blank string")
    return value.strip()


def _enum_value(enum_type: type[Enum], value: Any, field_name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise FixtureValidationError(f"invalid {field_name}: {value!r}") from exc


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise FixtureValidationError(f"{field_name} must be a non-empty sequence")
    items = tuple(_required_text(item, field_name) for item in value)
    if len(set(items)) != len(items):
        raise FixtureValidationError(f"{field_name} must not contain duplicates")
    return items


@dataclass(frozen=True)
class FixtureDefinition:
    fixture_id: str
    family: FixtureFamily
    title: str
    purpose: str
    criticality: Criticality
    required_semantics: tuple[str, ...]
    input_spec: Mapping[str, Any]
    expected_classification_domain: tuple[FixtureDisposition, ...]
    expected_exception_class: ExceptionClass | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FixtureDefinition":
        if not isinstance(data, Mapping):
            raise FixtureValidationError("fixture must be a mapping")

        fixture_id = _required_text(data.get("fixture_id"), "fixture_id")
        family = _enum_value(FixtureFamily, data.get("family"), "family")
        title = _required_text(data.get("title"), "title")
        purpose = _required_text(data.get("purpose"), "purpose")
        criticality = _enum_value(Criticality, data.get("criticality"), "criticality")
        required_semantics = _string_tuple(data.get("required_semantics"), "required_semantics")

        input_spec_raw = data.get("input_spec")
        if not isinstance(input_spec_raw, Mapping):
            raise FixtureValidationError("input_spec must be a mapping")
        input_spec = dict(input_spec_raw)

        expected_raw = data.get("expected_classification_domain")
        if not isinstance(expected_raw, (list, tuple)) or not expected_raw:
            raise FixtureValidationError("expected_classification_domain must be a non-empty sequence")
        expected = tuple(
            _enum_value(FixtureDisposition, value, "expected_classification_domain")
            for value in expected_raw
        )
        if len(set(expected)) != len(expected):
            raise FixtureValidationError("expected_classification_domain must not contain duplicates")

        exception_raw = data.get("expected_exception_class")
        expected_exception_class = None
        if exception_raw is not None:
            expected_exception_class = _enum_value(
                ExceptionClass,
                exception_raw,
                "expected_exception_class",
            )

        if family is FixtureFamily.AUTHORITY:
            groups = input_spec.get("required_path_groups")
            if not isinstance(groups, (list, tuple)) or not groups:
                raise FixtureValidationError("required_path_groups must be a non-empty sequence")
            normalized_groups: list[tuple[str, ...]] = []
            for group in groups:
                if not isinstance(group, (list, tuple)) or not group:
                    raise FixtureValidationError("required_path_groups must contain non-empty path groups")
                normalized_groups.append(_string_tuple(group, "required_path_groups"))
            input_spec["required_path_groups"] = tuple(normalized_groups)
            gap_value = input_spec.get("gap_class_if_absent")
            gap_class = _enum_value(ExceptionClass, gap_value, "gap_class_if_absent")
            input_spec["gap_class_if_absent"] = gap_class.value

        return cls(
            fixture_id=fixture_id,
            family=family,
            title=title,
            purpose=purpose,
            criticality=criticality,
            required_semantics=required_semantics,
            input_spec=input_spec,
            expected_classification_domain=expected,
            expected_exception_class=expected_exception_class,
        )


@dataclass(frozen=True)
class FixtureManifest:
    experiment_id: str
    fixture_set_version: str
    source_under_test_sha: str
    schema_version: str
    fixtures: tuple[FixtureDefinition, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FixtureManifest":
        if not isinstance(data, Mapping):
            raise FixtureValidationError("manifest must be a mapping")

        experiment_id = _required_text(data.get("experiment_id"), "experiment_id")
        fixture_set_version = _required_text(data.get("fixture_set_version"), "fixture_set_version")
        source_sha = _required_text(data.get("source_under_test_sha"), "source_under_test_sha")
        if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
            raise FixtureValidationError("source_under_test_sha must be 40 lowercase hexadecimal characters")
        schema_version = _required_text(data.get("schema_version"), "schema_version")

        fixtures_raw = data.get("fixtures")
        if not isinstance(fixtures_raw, (list, tuple)) or not fixtures_raw:
            raise FixtureValidationError("fixtures must be a non-empty sequence")
        fixtures = tuple(FixtureDefinition.from_dict(item) for item in fixtures_raw)
        ids = [fixture.fixture_id for fixture in fixtures]
        if len(ids) != len(set(ids)):
            raise FixtureValidationError("duplicate fixture_id")

        return cls(
            experiment_id=experiment_id,
            fixture_set_version=fixture_set_version,
            source_under_test_sha=source_sha,
            schema_version=schema_version,
            fixtures=fixtures,
        )


@dataclass(frozen=True)
class FixtureResult:
    result_id: str
    run_id: str
    attempt: int
    fixture_id: str
    disposition: FixtureDisposition
    source_under_test_sha: str
    schema_version: str
    fixture_manifest_sha256: str
    structured_fields_used: tuple[str, ...] = ()
    exception_class: ExceptionClass | None = None
    evidence_summary: str = ""
    error: str | None = None
    prior_result_id: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.result_id, "result_id")
        _required_text(self.run_id, "run_id")
        _required_text(self.fixture_id, "fixture_id")
        _required_text(self.source_under_test_sha, "source_under_test_sha")
        _required_text(self.schema_version, "schema_version")
        if re.fullmatch(r"[0-9a-f]{64}", self.fixture_manifest_sha256) is None:
            raise FixtureValidationError(
                "fixture_manifest_sha256 must be 64 lowercase hexadecimal characters"
            )
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise FixtureValidationError("attempt must be an integer >= 1")
        if not isinstance(self.disposition, FixtureDisposition):
            raise FixtureValidationError("disposition must be FixtureDisposition")
        if self.disposition is FixtureDisposition.NOT_COVERED and self.exception_class is None:
            raise FixtureValidationError("NOT_COVERED requires exception_class")
        if self.exception_class is not None and not isinstance(self.exception_class, ExceptionClass):
            raise FixtureValidationError("exception_class must be ExceptionClass")
        fields = tuple(_required_text(value, "structured_fields_used") for value in self.structured_fields_used)
        if len(fields) != len(set(fields)):
            raise FixtureValidationError("structured_fields_used must not contain duplicates")
        if self.prior_result_id is not None:
            _required_text(self.prior_result_id, "prior_result_id")
