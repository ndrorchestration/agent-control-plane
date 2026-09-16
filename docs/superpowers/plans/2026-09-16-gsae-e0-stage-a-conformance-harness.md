# GSAE-E0 Stage-A Conformance Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, research-isolated Stage-A apparatus that can measure whether ACP `agent-control-plane.execution.v1` represents the frozen GSAE-E0 governance semantics without modifying the contract under test or authorizing the experiment.

**Architecture:** Add an `experiments/gsae_e0/` package that contains immutable fixture definitions, typed validation, semantic-surface classification, native ACP conformance probes, deterministic evidence-manifest construction, and a fail-closed runner. The runner imports the existing ACP contract but ACP production modules never import the experiment package. Unit tests validate the apparatus with synthetic or already-established ACP behaviors; they must not execute the canonical frozen Stage-A manifest as an authorized experiment.

**Tech Stack:** Python 3.10–3.14, standard library (`dataclasses`, `enum`, `hashlib`, `json`, `pathlib`, `subprocess`, `uuid`), pytest, existing `agent_control_plane` package.

**Spec:** `docs/superpowers/specs/2026-09-16-gsae-e0-stage-a-conformance-harness-design.md`

## Global Constraints

- Source under test: ACP PR #5 exact head `07a09698ca66e8837d04e6ec05b4de3448eced04`.
- Candidate schema: `agent-control-plane.execution.v1`.
- Stage A must not modify any file under `src/agent_control_plane/`.
- No network/provider dependency is permitted.
- No Stage-B portability claim is permitted.
- Apparatus completion may establish only `APPARATUS_READY` or a narrower engineering status.
- GSAE-E0 remains `EXECUTION NOT AUTHORIZED / NOT RUN / N=0` until a separate authorization record exists.
- Free-form `detail`, opaque artifact payloads, overloaded status strings, and runtime-specific identifier conventions do not count as structured semantic coverage.
- Missing required evidence is `NOT_ESTABLISHED`; it is never imputed.
- Retries must preserve prior evidence and use distinct result identities.
- Existing repository verification remains `python -m pip install -e . pytest` followed by `python -m pytest` across Python 3.10–3.14.

---

## File Structure

Create or modify only these paths during apparatus implementation:

- Modify `pyproject.toml` — include experiment tests in pytest discovery.
- Create `experiments/gsae_e0/__init__.py` — package marker and intentionally small public surface.
- Create `experiments/gsae_e0/schema.py` — enums, fixture/result dataclasses, fail-closed validation.
- Create `experiments/gsae_e0/fixtures.py` — load frozen JSON and compute deterministic fixture identity.
- Create `experiments/gsae_e0/classify.py` — structured contract surface and pure per-fixture/aggregate classification.
- Create `experiments/gsae_e0/runner.py` — source binding, native observations, canonical-run guard, result-matrix orchestration.
- Create `experiments/gsae_e0/manifest.py` — deterministic evidence bundle construction/validation.
- Create `experiments/gsae_e0/fixtures/stage_a_v1.json` — frozen candidate Stage-A fixture set.
- Create `experiments/gsae_e0/README.md` — evidence ceiling, commands, authorization boundary.
- Create `experiments/gsae_e0/tests/test_fixture_schema.py` — fixture parsing/validation/hash tests.
- Create `experiments/gsae_e0/tests/test_classification.py` — structured-coverage and aggregate-rule tests using synthetic surfaces.
- Create `experiments/gsae_e0/tests/test_runner.py` — source-binding, native-observation, and execution-guard tests.
- Create `experiments/gsae_e0/tests/test_manifest.py` — deterministic evidence-bundle and retry-preservation tests.

Do **not** modify `src/agent_control_plane/contract/*`, `src/agent_control_plane/core.py`, `src/agent_control_plane/policy.py`, `src/agent_control_plane/provenance.py`, or `src/agent_control_plane/budget.py` in this plan.

---

### Task 1: Add experiment discovery and typed fixture schema

**Files:**
- Modify: `pyproject.toml`
- Create: `experiments/gsae_e0/__init__.py`
- Create: `experiments/gsae_e0/schema.py`
- Create: `experiments/gsae_e0/tests/test_fixture_schema.py`

**Interfaces:**
- Produces: `Criticality`, `FixtureFamily`, `ExceptionClass`, `FixtureDisposition`, `AggregateDisposition`, `FixtureDefinition`, `FixtureManifest`, `FixtureResult`, `FixtureValidationError`.
- Later tasks consume `FixtureDefinition.from_dict()`, `FixtureManifest.from_dict()`, and the exact enum values defined here.

- [ ] **Step 1: Write failing schema tests and enable pytest discovery**

Change pytest discovery to:

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests", "experiments/gsae_e0/tests"]
```

Create tests that require duplicate IDs, blank IDs, unknown enum values, empty semantic requirements, and malformed `input_spec` to fail closed:

```python
import pytest

from experiments.gsae_e0.schema import FixtureManifest, FixtureValidationError


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
```

- [ ] **Step 2: Run the targeted test and confirm RED**

Run:

```bash
python -m pytest experiments/gsae_e0/tests/test_fixture_schema.py -v
```

Expected: collection/import failure because `experiments.gsae_e0.schema` does not exist.

- [ ] **Step 3: Implement the minimal typed schema**

Use exact enum values:

```python
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
```

Implement frozen dataclasses. `FixtureDefinition.from_dict()` must require all documented fields, convert list fields to tuples, validate enum values, reject blank strings, and for `authority_semantic` fixtures require `input_spec.required_path_groups` to be a non-empty list of non-empty string lists plus a valid `gap_class_if_absent`. `FixtureManifest.from_dict()` must reject duplicate IDs and require non-empty `experiment_id`, `fixture_set_version`, `source_under_test_sha`, and `schema_version`.

`FixtureResult` must contain:

```python
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
```

Reject `attempt < 1`, blank identities, `NOT_COVERED` without `exception_class`, and duplicate/blank structured field names.

- [ ] **Step 4: Run the schema test and whole suite**

```bash
python -m pytest experiments/gsae_e0/tests/test_fixture_schema.py -v
python -m pytest
```

Expected: targeted PASS; existing ACP tests remain PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml experiments/gsae_e0/__init__.py experiments/gsae_e0/schema.py experiments/gsae_e0/tests/test_fixture_schema.py
git commit -m "test: add GSAE-E0 fixture schema"
```

---

### Task 2: Freeze the exact Stage-A fixture set and deterministic fixture identity

**Files:**
- Create: `experiments/gsae_e0/fixtures.py`
- Create: `experiments/gsae_e0/fixtures/stage_a_v1.json`
- Modify: `experiments/gsae_e0/tests/test_fixture_schema.py`

**Interfaces:**
- Produces: `load_fixture_manifest(path: Path) -> FixtureManifest`, `canonical_json_bytes(value: object) -> bytes`, `fixture_manifest_sha256(path: Path) -> str`.
- Later tasks consume the frozen manifest hash and exact fixture IDs.

- [ ] **Step 1: Add failing loader/hash/frozen-set tests**

```python
from pathlib import Path

from experiments.gsae_e0.fixtures import fixture_manifest_sha256, load_fixture_manifest

FIXTURE_PATH = Path("experiments/gsae_e0/fixtures/stage_a_v1.json")


def test_frozen_stage_a_fixture_ids_are_exact():
    manifest = load_fixture_manifest(FIXTURE_PATH)
    assert {f.fixture_id for f in manifest.fixtures} == {
        "NATIVE-01", "NATIVE-02", "NATIVE-03", "NATIVE-04", "NATIVE-05",
        "NATIVE-06", "NATIVE-07", "NATIVE-08", "NATIVE-09", "NATIVE-10",
        "NEG-01", "NEG-02", "NEG-03", "NEG-04", "NEG-05", "NEG-06", "NEG-07", "NEG-08",
        "AUTH-01", "AUTH-02", "AUTH-03", "AUTH-04", "AUTH-05",
        "AUTH-06", "AUTH-07", "AUTH-08", "AUTH-09", "AUTH-10",
    }


def test_fixture_hash_is_64_lower_hex_and_stable():
    first = fixture_manifest_sha256(FIXTURE_PATH)
    second = fixture_manifest_sha256(FIXTURE_PATH)
    assert first == second
    assert len(first) == 64
    assert first == first.lower()
```

- [ ] **Step 2: Run and confirm RED**

```bash
python -m pytest experiments/gsae_e0/tests/test_fixture_schema.py -v
```

Expected: FAIL because loader and frozen JSON do not exist.

- [ ] **Step 3: Implement canonical JSON and loader**

```python
def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def load_fixture_manifest(path: Path) -> FixtureManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return FixtureManifest.from_dict(data)


def fixture_manifest_sha256(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    FixtureManifest.from_dict(data)
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()
```

- [ ] **Step 4: Create the frozen fixture file with these exact semantics**

Header fields:

```json
{
  "experiment_id": "GSAE-E0",
  "fixture_set_version": "stage-a-v1",
  "source_under_test_sha": "07a09698ca66e8837d04e6ec05b4de3448eced04",
  "schema_version": "agent-control-plane.execution.v1",
  "fixtures": []
}
```

Populate `fixtures` with exactly the following definitions. All are `critical` unless explicitly stated otherwise.

| ID | family | required semantics / test intent | classification domain | authority path rule / expected rejection |
|---|---|---|---|---|
| NATIVE-01 | native_conformance | allowed ordinary completion | PASS, NOT_ESTABLISHED | dispatch `echo`, require completed event |
| NATIVE-02 | native_conformance | policy denial evidence | PASS, NOT_ESTABLISHED | policy returns `blocked`, require `task.denied` event |
| NATIVE-03 | native_conformance | unknown capability fail-closed evidence | PASS, NOT_ESTABLISHED | require `task.rejected` then `KeyError` |
| NATIVE-04 | native_conformance | handler failure evidence | PASS, NOT_ESTABLISHED | handler raises `RuntimeError`, require FAILED state/event |
| NATIVE-05 | native_conformance | cancellation evidence | PASS, NOT_ESTABLISHED | cancel CREATED task, require CANCELLED event |
| NATIVE-06 | native_conformance | cooperative budget exhaustion | PASS, NOT_ESTABLISHED | max_steps=0 then consume step, require BUDGET_EXHAUSTED |
| NATIVE-07 | native_conformance | artifact linkage | PASS, NOT_ESTABLISHED | construct event with one input and one output `ArtifactRef` |
| NATIVE-08 | native_conformance | trace parent/child linkage | PASS, NOT_ESTABLISHED | construct `TraceContext` with distinct parent/span |
| NATIVE-09 | native_conformance | policy decision reference binding | PASS, NOT_ESTABLISHED | construct event with `policy_decision_ref="decision-1"` |
| NATIVE-10 | native_conformance | legacy provenance mapping | PASS, NOT_ESTABLISHED | map matching run IDs and preserve event/task/capability/state |
| NEG-01 | negative_control | provenance/contract run mismatch | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| NEG-02 | negative_control | unsupported schema version | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| NEG-03 | negative_control | blank required identity | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| NEG-04 | negative_control | span self-parenting | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| NEG-05 | negative_control | malformed SHA-256 | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| NEG-06 | negative_control | negative/non-integer monotonic value | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| NEG-07 | negative_control | non-UTC/naive timestamp | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| NEG-08 | negative_control | malformed nested contract type | EXPECTED_REJECTION, NOT_ESTABLISHED | ContractValidationError |
| AUTH-01 | authority_semantic | principal / acting identity | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["principal.principal_id"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-02 | authority_semantic | requested capability | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["capability"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-03 | authority_semantic | resource / target scope | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["resource.resource_id"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-04 | authority_semantic | operation / action semantics distinct from generic capability | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["operation.action"]]`; gap `AMBIGUOUS_SEMANTIC` |
| AUTH-05 | authority_semantic | policy identity plus version/hash | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["policy.policy_id"], ["policy.version_or_hash"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-06 | authority_semantic | decision identity plus explicit allow/deny/conditional outcome | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["policy_decision_ref"], ["decision.outcome"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-07 | authority_semantic | lease / authority expiry | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["authority.expires_at"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-08 | authority_semantic | delegation chain / delegator scope | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["delegation.delegator_id"], ["delegation.scope"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-09 | authority_semantic | permitted/forbidden actions or authority conditions | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["authority.conditions"]]`; gap `MISSING_CORE_SEMANTIC` |
| AUTH-10 | authority_semantic | reason code plus decision-to-execution provenance link | STRUCTURED_COVERAGE, NOT_COVERED | groups `[["policy_decision_ref"], ["decision.reason_code"]]`; gap `MISSING_CORE_SEMANTIC` |

For each JSON object also supply a concrete `title`, one-sentence `purpose`, `required_semantics` containing the named semantic/test intent, and an `input_spec` object with the exact operation parameters above. Do not add alternate authority paths that rely on `detail`, artifact payload contents, or identifier conventions.

- [ ] **Step 5: Run targeted and full tests**

```bash
python -m pytest experiments/gsae_e0/tests/test_fixture_schema.py -v
python -m pytest
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add experiments/gsae_e0/fixtures.py experiments/gsae_e0/fixtures/stage_a_v1.json experiments/gsae_e0/tests/test_fixture_schema.py
git commit -m "feat: freeze GSAE-E0 Stage-A fixtures"
```

---

### Task 3: Implement pure structured-coverage classification and aggregate rules

**Files:**
- Create: `experiments/gsae_e0/classify.py`
- Create: `experiments/gsae_e0/tests/test_classification.py`

**Interfaces:**
- Produces: `execution_v1_surface_paths() -> frozenset[str]`, `classify_authority_fixture(...) -> FixtureResult`, `aggregate_disposition(fixtures, results) -> AggregateDisposition`.
- Does not execute the frozen manifest in tests.

- [ ] **Step 1: Write failing tests using synthetic surfaces**

```python
from experiments.gsae_e0.classify import aggregate_disposition, classify_authority_fixture
from experiments.gsae_e0.schema import AggregateDisposition, ExceptionClass, FixtureDisposition


def test_detail_escape_hatch_does_not_count_as_structured_coverage(auth_fixture, result_context):
    result = classify_authority_fixture(auth_fixture, frozenset({"detail"}), **result_context)
    assert result.disposition is FixtureDisposition.NOT_COVERED
    assert result.exception_class is ExceptionClass.MISSING_CORE_SEMANTIC


def test_all_required_path_groups_must_be_satisfied(auth_fixture_two_groups, result_context):
    result = classify_authority_fixture(
        auth_fixture_two_groups,
        frozenset({"policy_decision_ref"}),
        **result_context,
    )
    assert result.disposition is FixtureDisposition.NOT_COVERED


def test_critical_missing_semantic_forces_not_feasible(critical_fixture, missing_result):
    assert aggregate_disposition((critical_fixture,), (missing_result,)) is AggregateDisposition.NOT_FEASIBLE


def test_missing_result_for_required_fixture_forces_not_established(critical_fixture):
    assert aggregate_disposition((critical_fixture,), ()) is AggregateDisposition.NOT_ESTABLISHED
```

Also test that `PROVENANCE_GAP`/`NOT_ESTABLISHED` results force aggregate `NOT_ESTABLISHED`, and a noncritical `NOT_COVERED` result with all critical fixtures satisfied yields `CONDITIONALLY_FEASIBLE_NARROW`.

- [ ] **Step 2: Run and confirm RED**

```bash
python -m pytest experiments/gsae_e0/tests/test_classification.py -v
```

Expected: import failure for `classify`.

- [ ] **Step 3: Implement contract-surface extraction without semantic invention**

Use `dataclasses.fields()` to enumerate only actual typed fields from `ExecutionEvent`, `ExecutionIdentity`, `TraceContext`, `ComponentIdentity`, and `ArtifactRef`.

The surface must include paths such as:

```python
{
    "event_type", "task_id", "status", "utc_timestamp", "monotonic_ns",
    "capability", "policy_decision_ref", "detail",
    "identity.execution_id", "identity.run_id", "identity.schema_version",
    "trace.trace_id", "trace.span_id", "trace.parent_span_id",
    "component.component_id", "component.component_type", "component.runtime_id",
    "component.adapter_id", "component.version", "component.source_ref",
    "input_artifacts[].artifact_id", "input_artifacts[].kind", "input_artifacts[].uri",
    "input_artifacts[].version", "input_artifacts[].sha256",
    "output_artifacts[].artifact_id", "output_artifacts[].kind", "output_artifacts[].uri",
    "output_artifacts[].version", "output_artifacts[].sha256",
}
```

Do not add conceptual aliases such as `operation.action` unless they are real typed fields.

- [ ] **Step 4: Implement pure authority classification**

For each `required_path_groups` group, at least one listed path must exist in the supplied surface. All groups must pass. If they do, return `STRUCTURED_COVERAGE` with the exact matched paths. If any group fails, return `NOT_COVERED` with the fixture's declared `gap_class_if_absent`.

Explicitly reject `detail`, `input_artifacts[].uri`, `output_artifacts[].uri`, and arbitrary identifier-string conventions as substitutes unless the fixture itself requires those exact technical fields for a non-authority-native test.

- [ ] **Step 5: Implement aggregate rules**

Order of precedence:

```python
# 1. Missing fixture result, invalid/unknown fixture result, or any required result
#    with NOT_ESTABLISHED / PROVENANCE_GAP / IMPLEMENTATION_DEFECT -> NOT_ESTABLISHED.
# 2. Critical NOT_COVERED due to MISSING_CORE_SEMANTIC, AMBIGUOUS_SEMANTIC,
#    RUNTIME_SPECIFIC, or ADAPTER_COMPLEXITY -> NOT_FEASIBLE_FOR_FROZEN_SCOPE.
# 3. All critical fixtures satisfied but >=1 noncritical NOT_COVERED ->
#    CONDITIONALLY_FEASIBLE_NARROW.
# 4. Otherwise -> FEASIBLE_FOR_FROZEN_SCOPE.
```

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest experiments/gsae_e0/tests/test_classification.py -v
python -m pytest
git add experiments/gsae_e0/classify.py experiments/gsae_e0/tests/test_classification.py
git commit -m "feat: add GSAE-E0 semantic classification"
```

---

### Task 4: Implement source binding and native ACP observation helpers

**Files:**
- Create: `experiments/gsae_e0/runner.py`
- Create: `experiments/gsae_e0/tests/test_runner.py`

**Interfaces:**
- Produces: `verify_source_binding(repo_root: Path, expected_sha: str) -> None`, `observe_native_fixture(fixture_id: str) -> tuple[FixtureDisposition, str]`.
- `verify_source_binding` verifies exact source ancestry and zero diff under `src/agent_control_plane/` relative to the source-under-test commit.

- [ ] **Step 1: Write failing source-binding tests**

```python
from pathlib import Path
import pytest

from experiments.gsae_e0.runner import SourceBindingError, verify_source_binding

SOURCE_SHA = "07a09698ca66e8837d04e6ec05b4de3448eced04"


def test_bound_source_is_ancestor_and_acp_package_is_unchanged():
    verify_source_binding(Path.cwd(), SOURCE_SHA)


def test_unknown_source_sha_fails_closed():
    with pytest.raises(SourceBindingError):
        verify_source_binding(Path.cwd(), "0" * 40)
```

Implementation must execute both:

```bash
git merge-base --is-ancestor <expected_sha> HEAD
git diff --quiet <expected_sha> -- src/agent_control_plane
```

Any nonzero exit status raises `SourceBindingError`.

- [ ] **Step 2: Add failing native observation tests**

Test only already-established ACP behaviors, one helper at a time; do not load/run the canonical Stage-A manifest:

```python
def test_native_allowed_completion_observation_passes():
    disposition, summary = observe_native_fixture("NATIVE-01")
    assert disposition is FixtureDisposition.PASS
    assert "task.completed" in summary


def test_unknown_capability_observation_requires_rejection_evidence():
    disposition, summary = observe_native_fixture("NATIVE-03")
    assert disposition is FixtureDisposition.PASS
    assert "task.rejected" in summary


def test_negative_run_mismatch_is_expected_rejection():
    disposition, summary = observe_native_fixture("NEG-01")
    assert disposition is FixtureDisposition.EXPECTED_REJECTION
    assert "run_id" in summary
```

Add equivalent tests for NATIVE-02 through NATIVE-10 and NEG-02 through NEG-08, but each test must invoke only one fixture helper and assert its exact expected evidence condition.

- [ ] **Step 3: Run and confirm RED**

```bash
python -m pytest experiments/gsae_e0/tests/test_runner.py -v
```

- [ ] **Step 4: Implement source binding and native observations**

Use existing public APIs only:

```python
from agent_control_plane import ControlPlane, ExecutionBudget, Task, TaskState
from agent_control_plane.contract import (
    ArtifactRef, ComponentIdentity, ContractValidationError, ExecutionEvent,
    ExecutionIdentity, TraceContext, map_provenance_event,
)
```

`observe_native_fixture()` must be an explicit dispatch table from known fixture ID to a focused helper. Unknown IDs raise `ValueError`; they must never silently pass.

Examples:

```python
def _native_01():
    plane = ControlPlane(run_id="gsae-e0-native-01")
    plane.register("echo", lambda task: task.payload)
    task = plane.dispatch("echo", Task(payload="hello", id="task-native-01"))
    if task.state is not TaskState.COMPLETED:
        return FixtureDisposition.NOT_ESTABLISHED, f"unexpected state={task.state.value}"
    if not any(event.event == "task.completed" for event in plane.events):
        return FixtureDisposition.NOT_ESTABLISHED, "missing task.completed evidence"
    return FixtureDisposition.PASS, "task.completed recorded"
```

For policy denial, assert the `task.denied` event rather than inventing a terminal DENIED task state. For negative controls, only return `EXPECTED_REJECTION` when the exact expected `ContractValidationError` occurs.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest experiments/gsae_e0/tests/test_runner.py -v
python -m pytest
git add experiments/gsae_e0/runner.py experiments/gsae_e0/tests/test_runner.py
git commit -m "feat: add GSAE-E0 native conformance observations"
```

---

### Task 5: Add deterministic evidence-manifest construction and validation

**Files:**
- Create: `experiments/gsae_e0/manifest.py`
- Create: `experiments/gsae_e0/tests/test_manifest.py`

**Interfaces:**
- Produces: `EvidenceBundle`, `build_evidence_bundle(...)`, `validate_evidence_bundle(...)`, `canonical_bundle_sha256(...)`, `result_id(run_id, fixture_id, attempt) -> str`.

- [ ] **Step 1: Write failing determinism and retry tests**

```python
from experiments.gsae_e0.manifest import canonical_bundle_sha256, result_id


def test_result_id_is_deterministic_per_attempt_and_changes_on_retry():
    first = result_id("run-1", "AUTH-01", 1)
    same = result_id("run-1", "AUTH-01", 1)
    retry = result_id("run-1", "AUTH-01", 2)
    assert first == same
    assert first != retry


def test_semantically_identical_bundle_hash_is_stable(bundle):
    assert canonical_bundle_sha256(bundle) == canonical_bundle_sha256(bundle)


def test_missing_result_identity_is_rejected(bundle_without_result_id):
    with pytest.raises(EvidenceValidationError, match="result_id"):
        validate_evidence_bundle(bundle_without_result_id)
```

Also test duplicate result IDs, unknown fixture IDs, mismatched source SHA, mismatched schema version, mismatched fixture hash, and a retry whose `prior_result_id` does not point to the prior attempt.

- [ ] **Step 2: Run and confirm RED**

```bash
python -m pytest experiments/gsae_e0/tests/test_manifest.py -v
```

- [ ] **Step 3: Implement deterministic identities and evidence bundle**

Use UUIDv5 for result IDs so IDs are deterministic from the immutable tuple while retries remain distinct:

```python
_RESULT_NAMESPACE = UUID("e063a317-67cb-5d84-a411-7027376c68a0")


def result_id(run_id: str, fixture_id: str, attempt: int) -> str:
    if attempt < 1:
        raise EvidenceValidationError("attempt must be >= 1")
    return str(uuid5(_RESULT_NAMESPACE, f"{run_id}|{fixture_id}|{attempt}"))
```

`EvidenceBundle` must contain at least:

```python
experiment_id
protocol_version
run_id
authorization_record_id
source_under_test_sha
harness_commit_sha
schema_version
fixture_set_version
fixture_manifest_sha256
results
aggregate_disposition
test_command
test_summary
evidence_ceiling
```

Canonical serialization uses sorted keys and compact separators. Do not include wall-clock timestamps in the hash-bearing semantic body; if later retained as metadata, keep them in a separately excluded provenance envelope.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest experiments/gsae_e0/tests/test_manifest.py -v
python -m pytest
git add experiments/gsae_e0/manifest.py experiments/gsae_e0/tests/test_manifest.py
git commit -m "feat: add deterministic GSAE-E0 evidence bundles"
```

---

### Task 6: Add the fail-closed canonical Stage-A runner without executing it

**Files:**
- Modify: `experiments/gsae_e0/runner.py`
- Modify: `experiments/gsae_e0/tests/test_runner.py`

**Interfaces:**
- Produces: `run_stage_a(...) -> EvidenceBundle`.
- This function is apparatus only. CI tests its guards using temporary/synthetic manifests; tests must not invoke it with the frozen `stage_a_v1.json` plus a real authorization record.

- [ ] **Step 1: Write failing guard tests**

Exact function signature:

```python
def run_stage_a(
    *,
    repo_root: Path,
    fixture_path: Path,
    protocol_version: str,
    authorization_record_id: str,
    run_id: str,
    harness_commit_sha: str,
    test_command: str,
    test_summary: str,
) -> EvidenceBundle:
    ...
```

Tests:

```python
def test_run_rejects_blank_authorization_record_id(synthetic_manifest_path):
    with pytest.raises(ExecutionGuardError, match="authorization_record_id"):
        run_stage_a(
            repo_root=Path.cwd(),
            fixture_path=synthetic_manifest_path,
            protocol_version="GSAE-E0-R2-v0.1",
            authorization_record_id="",
            run_id="synthetic-run",
            harness_commit_sha="a" * 40,
            test_command="python -m pytest",
            test_summary="synthetic apparatus test",
        )


def test_run_rejects_wrong_experiment_id(synthetic_wrong_experiment_manifest_path):
    with pytest.raises(ExecutionGuardError, match="GSAE-E0"):
        ...
```

Also test blank protocol/run/harness identities, schema mismatch, and source-binding failure. These are guard tests, not experiment execution.

- [ ] **Step 2: Run and confirm RED**

```bash
python -m pytest experiments/gsae_e0/tests/test_runner.py -v
```

- [ ] **Step 3: Implement orchestration**

`run_stage_a()` must perform this exact order:

1. reject blank execution/provenance identities;
2. load and validate fixture manifest;
3. require `experiment_id == "GSAE-E0"`;
4. require `schema_version == SCHEMA_VERSION`;
5. verify exact source binding before fixture evaluation;
6. compute frozen fixture-manifest SHA-256;
7. evaluate native/negative fixtures through `observe_native_fixture()`;
8. evaluate authority fixtures using `execution_v1_surface_paths()` and `classify_authority_fixture()`;
9. require exactly one result per frozen fixture ID;
10. derive aggregate disposition;
11. build and validate the evidence bundle;
12. return the bundle without writing files or mutating ACP state.

The runner itself must not decide whether the supplied authorization record is politically/organizationally valid; it records the explicit identifier and fails on absence. The owning GSAE control record remains the authorization authority.

- [ ] **Step 4: Add an explicit test preventing accidental canonical execution in CI**

```python
def test_ci_suite_does_not_call_canonical_stage_a_runner(monkeypatch):
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("canonical Stage-A execution is not a unit test")

    monkeypatch.setattr("experiments.gsae_e0.runner._execute_frozen_manifest", forbidden, raising=False)
    assert called is False
```

More importantly, search the experiment tests and ensure no test passes `experiments/gsae_e0/fixtures/stage_a_v1.json` to `run_stage_a()`.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest experiments/gsae_e0/tests/test_runner.py -v
python -m pytest
git add experiments/gsae_e0/runner.py experiments/gsae_e0/tests/test_runner.py
git commit -m "feat: add guarded GSAE-E0 Stage-A runner"
```

---

### Task 7: Document apparatus use and evidence ceiling

**Files:**
- Create: `experiments/gsae_e0/README.md`

**Interfaces:**
- Documentation only; no new runtime behavior.

- [ ] **Step 1: Write the README with exact current state**

It must state:

```markdown
# GSAE-E0 Stage-A Conformance Harness

Status: RESEARCH APPARATUS / EXECUTION NOT AUTHORIZED / NOT RUN / N=0

Source under test: `07a09698ca66e8837d04e6ec05b4de3448eced04`
Schema: `agent-control-plane.execution.v1`
Frozen fixture candidate: `fixtures/stage_a_v1.json`

This package measures contract feasibility only. Passing apparatus tests do not establish
GSAE-E0 feasibility, portability, governance efficacy, safety, security, production
readiness, or authorization.
```

Document:
- setup: `python -m pip install -e . pytest`;
- apparatus verification: `python -m pytest experiments/gsae_e0/tests -v`;
- full repository verification: `python -m pytest`;
- the source-binding rule;
- the authorization boundary;
- the four possible aggregate dispositions;
- the rule that canonical Stage-A execution occurs only after an explicit owning-control-record authorization event;
- the prohibition on modifying the contract before freezing Stage-A evidence if the experiment finds missing semantics.

Do not include a copy-paste command that executes the frozen canonical experiment while it remains unauthorized.

- [ ] **Step 2: Verify documentation does not overclaim**

Run:

```bash
grep -R "AUTHORIZED\|FEASIBLE\|portable\|production" experiments/gsae_e0/README.md
```

Manually confirm every occurrence is bounded or negated appropriately.

- [ ] **Step 3: Commit**

```bash
git add experiments/gsae_e0/README.md
git commit -m "docs: bound GSAE-E0 apparatus evidence ceiling"
```

---

### Task 8: Final apparatus verification and repository handoff

**Files:**
- No code files should need changes unless verification finds a defect.
- Update GitHub issue #6 only after exact-head verification succeeds.

**Interfaces:**
- Produces repository-level `APPARATUS_READY` evidence only if all checks pass.

- [ ] **Step 1: Verify ACP source-under-test files were not modified**

```bash
git diff --exit-code 07a09698ca66e8837d04e6ec05b4de3448eced04 -- src/agent_control_plane
```

Expected: no output, exit 0.

- [ ] **Step 2: Run experiment-apparatus tests**

```bash
python -m pip install -e . pytest
python -m pytest experiments/gsae_e0/tests -v
```

Expected: all apparatus tests PASS.

- [ ] **Step 3: Run full repository suite**

```bash
python -m pytest
```

Expected: all ACP + contract + apparatus tests PASS.

- [ ] **Step 4: Compute exact fixture identity and record exact apparatus head**

```bash
python - <<'PY'
from pathlib import Path
from experiments.gsae_e0.fixtures import fixture_manifest_sha256
print(fixture_manifest_sha256(Path("experiments/gsae_e0/fixtures/stage_a_v1.json")))
PY
git rev-parse HEAD
```

Record both exact values without abbreviation.

- [ ] **Step 5: Confirm no canonical E0 evidence bundle was produced**

```bash
find experiments/gsae_e0 -type f \( -name '*result*.json' -o -name '*evidence*.json' -o -name '*run*.json' \) -print
```

Expected: no canonical run/result artifact. Source JSON fixtures are permitted.

- [ ] **Step 6: Update GitHub issue #6**

Record:
- exact apparatus head;
- fixture-manifest SHA-256;
- exact commands and test counts;
- confirmation that `src/agent_control_plane/` is unchanged relative to the source-under-test commit;
- status `APPARATUS_READY` if and only if all verification above passes;
- explicit `GSAE-E0 EXECUTION NOT AUTHORIZED / NOT RUN / N=0`;
- next gate: owning GSAE protocol-freeze acceptance, then separate execution authorization.

- [ ] **Step 7: Open a review PR from `research/gsae-e0-stage-a-harness`**

PR title:

```text
research: add GSAE-E0 Stage-A conformance apparatus
```

PR body must separate:
- implementation changes;
- test/verification evidence;
- source-under-test binding;
- evidence ceiling;
- known semantic findings, if any are discovered during apparatus construction, labeled as non-canonical until authorized execution;
- unchanged scientific/governance state.

- [ ] **Step 8: Verify PR CI on the exact head**

Require all Python 3.10, 3.11, 3.12, 3.13, and 3.14 jobs to succeed. Do not call apparatus readiness verified until exact-head CI is green.

---

## Plan Self-Review Result

- **Spec coverage:** all design sections are mapped: isolated architecture, exact source binding, fixture taxonomy, AUTH-01–AUTH-10, structured-coverage rule, exception taxonomy, deterministic results, aggregate dispositions, runner behavior, evidence bundle, fail-closed rules, testing, PR #5 relationship, governance boundary, and completion criteria.
- **No canonical-run leakage:** unit/CI work validates the apparatus and already-established ACP behaviors only. The canonical frozen Stage-A manifest is not passed to `run_stage_a()` in tests.
- **Type consistency:** enum strings, fixture/result fields, runner inputs, and evidence-bundle identities are consistent across tasks.
- **No ACP contract mutation:** final verification explicitly proves `src/agent_control_plane/` is unchanged from the source-under-test commit.
- **No placeholders:** all required files, commands, identities, fixture IDs, semantic path rules, and status transitions are explicit.
