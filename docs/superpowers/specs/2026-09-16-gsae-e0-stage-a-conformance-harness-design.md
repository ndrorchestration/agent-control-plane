# GSAE-E0 Stage-A Conformance Harness — Design

Date: 2026-09-16  
Status: APPROVED DESIGN / SPEC REVIEW PENDING  
Repository: `ndrorchestration/agent-control-plane`  
Source-under-test lineage: PR #5 exact head `07a09698ca66e8837d04e6ec05b4de3448eced04`  
Candidate schema: `agent-control-plane.execution.v1`

## 1. Purpose

Build a research-scoped, deterministic conformance harness for `GSAE-E0` that tests whether the current ACP execution contract can represent frozen ordinary and consequential governance states without semantic overload, runtime-specific reinterpretation, or a core-schema fork.

This apparatus is evidence-producing research infrastructure only. It must not change the ACP contract under test, authorize GSAE-E0 execution, establish portability, establish DGAF/GSAE efficacy, or imply production/security readiness.

## 2. Design principle

The harness measures the contract before attempting to improve it. Stage A imports the exact bound contract implementation and treats missing or ambiguous semantics as results. It must not encode missing governance meanings into free-form `detail`, opaque artifact references, or runtime-specific strings and then count those encodings as structured coverage.

## 3. Scope

In scope:

- deterministic fixture definitions;
- exact source/schema/fixture identity binding;
- native ACP conformance fixtures;
- governance-authority semantic probes `AUTH-01` through `AUTH-10`;
- negative controls for malformed or mismatched inputs;
- explicit exception classification;
- deterministic result-matrix generation;
- machine-readable evidence manifests;
- fail-closed fixture/result validation;
- tests for determinism, identity binding, classification, and negative controls.

Out of scope:

- changing `agent-control-plane.execution.v1` during Stage A;
- adding a second runtime or claiming portability;
- provider/network integrations;
- DGAF/GSAE authorization or efficacy conclusions;
- production/security certification;
- durable or tamper-evident provenance claims;
- autonomous/self-improving runtime behavior;
- schema redesign before the Stage-A evidence package is frozen.

## 4. Repository layout

Use a research-isolated package:

```text
experiments/gsae_e0/
  __init__.py
  README.md
  schema.py
  fixtures.py
  classify.py
  runner.py
  manifest.py
  fixtures/
    stage_a_v1.json
  tests/
    test_fixture_schema.py
    test_classification.py
    test_runner.py
    test_manifest.py
```

The package may import public ACP contract types from `agent_control_plane.contract`. ACP production modules must not import from `experiments.gsae_e0`.

## 5. Fixed source binding

Every Stage-A evidence bundle must bind repository identity, exact source-under-test SHA, schema version, fixture-set version, fixture-manifest SHA-256, harness commit SHA, test command, and run/result identity.

A source-under-test SHA change invalidates the previous bundle for current-state claims and requires explicit rebind/re-run. Historical results remain provenance.

Initial source under test:

`07a09698ca66e8837d04e6ec05b4de3448eced04`

Its open PR status is metadata only and is not evidence that the implementation is accepted on `main`.

## 6. Fixture model

Each fixture is immutable by identifier within a fixture-set version and contains at minimum:

- `fixture_id`;
- `family`;
- `title`;
- `purpose`;
- `criticality` (`critical` or `noncritical`);
- `required_semantics`;
- `input_spec`;
- `expected_classification_domain`;
- optional expected exception class for negative controls.

Malformed fixture definitions fail closed before execution and produce no conformance result.

### Native conformance fixtures

1. allowed ordinary completion;
2. policy denial;
3. unknown-capability rejection;
4. handler/runtime failure;
5. cancellation;
6. cooperative budget exhaustion;
7. input/output artifact linkage;
8. trace parent/child linkage;
9. policy-decision reference binding;
10. legacy provenance to execution-contract mapping;
11. provenance/contract run-ID mismatch rejection;
12. malformed schema/identity/timestamp/hash/nested-contract rejection.

### Governance-authority probes

- `AUTH-01`: principal / acting identity;
- `AUTH-02`: requested capability;
- `AUTH-03`: resource / target scope;
- `AUTH-04`: operation / action semantics;
- `AUTH-05`: policy identity plus version/hash binding;
- `AUTH-06`: decision identity and explicit allow/deny/conditional semantics;
- `AUTH-07`: lease / authority expiry;
- `AUTH-08`: delegation chain / delegator scope;
- `AUTH-09`: permitted/forbidden actions or authority conditions;
- `AUTH-10`: reason codes plus decision-to-execution provenance linkage.

## 7. Structured-coverage rule

A semantic requirement counts as `STRUCTURED_COVERAGE` only when it has a stable, machine-addressable field or typed composition in the contract under test with a meaning that does not depend on free-form prose or runtime-specific reinterpretation.

The following do not count as structured coverage by themselves:

- `detail` strings;
- arbitrary artifact payload contents;
- overloaded `status` values;
- runtime-specific conventions embedded in identifiers;
- external documentation not represented in the contract instance.

This prevents the harness from manufacturing coverage through generic escape hatches.

## 8. Exception taxonomy

Every non-covered or failed fixture receives exactly one primary class:

- `MISSING_CORE_SEMANTIC`;
- `AMBIGUOUS_SEMANTIC`;
- `RUNTIME_SPECIFIC`;
- `ADAPTER_COMPLEXITY`;
- `NONCRITICAL_EXTENSION`;
- `MALFORMED_INPUT`;
- `IMPLEMENTATION_DEFECT`;
- `PROVENANCE_GAP`.

Explanatory notes may accompany the result, but the primary class remains machine-readable.

## 9. Result model

Each fixture result records result identity, fixture identity, source/schema/fixture binding, disposition, primary exception class when applicable, structured fields used, deterministic evidence summary, error information for rejected/malformed cases, and immutable retry linkage.

A retry receives a new result identity and must never overwrite prior evidence. Timestamps may be retained as provenance metadata but are not semantic ordering authority.

## 10. Aggregate disposition

Stage A may produce only:

- `FEASIBLE_FOR_FROZEN_SCOPE`;
- `CONDITIONALLY_FEASIBLE_NARROW`;
- `NOT_FEASIBLE_FOR_FROZEN_SCOPE`;
- `NOT_ESTABLISHED`.

Rules:

- missing required evidence yields `NOT_ESTABLISHED`;
- a critical `MISSING_CORE_SEMANTIC` or `AMBIGUOUS_SEMANTIC` cannot be overridden by a high coverage percentage;
- `FEASIBLE_FOR_FROZEN_SCOPE` requires structured coverage for every critical frozen semantic plus passing required negative controls;
- `CONDITIONALLY_FEASIBLE_NARROW` requires uncovered items to be noncritical to a clearly stated narrower scope;
- `NOT_FEASIBLE_FOR_FROZEN_SCOPE` applies when one or more critical frozen semantics cannot be represented without violating the structured-coverage rule.

The aggregate is a contract-feasibility result only, never an authorization, safety, efficacy, portability, or production-readiness conclusion.

## 11. Runner behavior

The runner must:

1. validate the fixture manifest;
2. verify exact source/schema binding;
3. compute the fixture-manifest hash;
4. execute native conformance fixtures deterministically;
5. evaluate authority-semantic probes against the typed contract surface;
6. classify each fixture without mutating the contract implementation;
7. emit a stable machine-readable result matrix;
8. derive the bounded aggregate disposition;
9. emit an evidence manifest linking component identities and hashes.

No network access or provider dependency is permitted in Stage A.

## 12. Evidence bundle

The canonical Stage-A evidence bundle consists of:

- frozen fixture manifest;
- fixture-manifest SHA-256;
- source-under-test identity;
- harness identity;
- result matrix;
- aggregate disposition;
- test-output summary;
- evidence manifest linking component identities/hashes.

The bundle format must be deterministic apart from explicitly excluded runtime metadata. Timestamps, if present, must not affect semantic equality of result content.

## 13. Fail-closed rules

- malformed fixture manifest: reject run as `NOT_ESTABLISHED`;
- source/schema mismatch: reject run as `NOT_ESTABLISHED`;
- unexpected fixture execution exception: `IMPLEMENTATION_DEFECT` unless evidence establishes another class;
- missing required result field: reject evidence bundle;
- invalid result classification: reject evidence bundle;
- unknown fixture ID in output: reject evidence bundle;
- duplicate result identity: reject evidence bundle;
- missing critical fixture: aggregate `NOT_ESTABLISHED`;
- attempted free-form escape-hatch substitution: classify the semantic `AMBIGUOUS_SEMANTIC` or `MISSING_CORE_SEMANTIC`, never PASS.

## 14. Testing strategy

Tests establish apparatus behavior only, not GSAE-E0 feasibility.

Required tests:

- valid frozen fixture schema accepted;
- malformed/duplicate fixture definitions rejected where required;
- manifest hash deterministic;
- source-binding mismatch fails closed;
- every taxonomy class reachable through deterministic synthetic cases;
- structured-coverage rule rejects generic `detail`/opaque-artifact substitution;
- native fixtures reproduce already-established ACP contract behavior without changing ACP code;
- result ordering deterministic;
- aggregate disposition obeys criticality rules;
- retries create distinct identities and preserve prior evidence;
- evidence manifest rejects missing/mismatched identities.

Implementation must use TDD: failing apparatus tests precede implementation for each behavior slice.

## 15. Relationship to PR #5

PR #5 remains the exact source-under-test candidate. Stage A does not modify that PR's contract implementation.

The harness branch is based on PR #5 exact head so it can import the candidate contract directly. Harness findings must be reviewed separately from the contract candidate. If Stage A later motivates schema changes, those changes belong in a subsequent explicit contract revision after the Stage-A evidence bundle is frozen.

## 16. Governance relationship

Notion remains the interpreted GSAE-E0 research/governance SSoT. GitHub remains authoritative for exact code, commit, issue, PR, CI, and evidence-artifact identities.

Apparatus completion may advance only to `APPARATUS_READY`. It must not mark:

- `PROTOCOL FROZEN` unless the owning GSAE record explicitly records the freeze;
- `EXECUTION AUTHORIZED` without a separate authorization event;
- `RUN` or scientific `N>0` before an actually authorized experiment;
- portability, efficacy, safety, or production-readiness claims.

## 17. Completion criteria

The subsystem is implementation-complete when:

1. all native fixture families exist in the frozen manifest;
2. `AUTH-01` through `AUTH-10` are represented;
3. deterministic tests pass on the exact apparatus head;
4. source/schema/fixture binding is enforced fail-closed;
5. the evidence manifest is deterministic and validated;
6. negative controls demonstrate malformed evidence rejection;
7. no ACP core/schema file is modified by the harness implementation;
8. repository documentation states the evidence ceiling;
9. GitHub issue #6 records exact apparatus head, test command/result, fixture hash, and `APPARATUS_READY` or narrower status.

These criteria establish measurement-apparatus readiness only.