# Cross-Runtime Execution Contract v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned framework-neutral execution/trace contract to ACP without changing existing kernel behavior or the `agent-control-plane.provenance.v1` manifest.

**Architecture:** Introduce focused immutable contract dataclasses plus strict validators in a new `agent_control_plane.contract` package. Keep the existing kernel/provenance model intact, then add an explicit mapper from legacy `ProvenanceEvent` into the new contract when the caller supplies trace/component context that legacy events do not contain.

**Tech Stack:** Python >=3.10, stdlib dataclasses/datetime/re, pytest, existing GitHub Actions matrix Python 3.10–3.14.

**Spec:** `docs/superpowers/specs/2026-09-14-cross-runtime-execution-contract-design.md`

## Global Constraints

- Contract schema version is exactly `agent-control-plane.execution.v1`.
- Canonical serialized UTC timestamps end in `Z`.
- Legacy provenance with absent state maps exactly to `unspecified`.
- Invalid required identity, unsupported schema version, malformed SHA-256, non-UTC timestamp, negative monotonic value, span self-parenting, and provenance/identity run mismatch fail closed with `ContractValidationError`.
- No new external dependencies.
- Existing `Task`, `ControlPlane`, budgets, public imports, and `agent-control-plane.provenance.v1` behavior remain compatible.
- This slice establishes ACP-native schema/serialization conformance only; portability remains NOT ESTABLISHED.

---

### Task 1: Core identities and validation

**Files:**
- Create: `tests/test_contract.py`
- Create: `src/agent_control_plane/contract/__init__.py`
- Create: `src/agent_control_plane/contract/model.py`

**Interfaces:**
- Produces: `ContractValidationError`, `ExecutionIdentity`, `TraceContext`, `ComponentIdentity`, `ArtifactRef`, `SCHEMA_VERSION`.

- [ ] **Step 1: Write failing tests** for valid deterministic serialization and each required rejection path: blank identity, unsupported schema version, blank trace/span, blank optional parent, self-parent, blank component fields, and malformed artifact SHA-256.
- [ ] **Step 2: Push tests only and verify RED in GitHub Actions.** Expected failures are import/definition failures for `agent_control_plane.contract` or missing required contract classes, not syntax/configuration failures.
- [ ] **Step 3: Implement minimal immutable dataclasses and validators** in `model.py`; export them through `contract/__init__.py`.
- [ ] **Step 4: Push implementation and verify GREEN** for the full Python 3.10–3.14 matrix.

### Task 2: Execution event and canonical time serialization

**Files:**
- Modify: `tests/test_contract.py`
- Modify: `src/agent_control_plane/contract/model.py`
- Modify: `src/agent_control_plane/contract/__init__.py`

**Interfaces:**
- Produces: `ExecutionEvent` with `to_dict()` and strict UTC/monotonic validation.
- Consumes: identities and artifact refs from Task 1.

- [ ] **Step 1: Write failing tests** for exact full-event dictionary serialization, canonical `Z` timestamp output, artifact order preservation, negative monotonic rejection, naive timestamp rejection, and non-UTC offset rejection.
- [ ] **Step 2: Push tests only and verify RED** for missing `ExecutionEvent`/event validation behavior.
- [ ] **Step 3: Implement the minimum event type and timestamp canonicalizer** needed to satisfy the tests; no generated timestamps during serialization.
- [ ] **Step 4: Push and verify GREEN** across the matrix.

### Task 3: Legacy provenance mapper

**Files:**
- Create: `src/agent_control_plane/contract/mapping.py`
- Modify: `src/agent_control_plane/contract/__init__.py`
- Modify: `tests/test_contract.py`

**Interfaces:**
- Produces: `map_provenance_event(event, *, identity, trace, component, monotonic_ns, input_artifacts=(), output_artifacts=(), policy_decision_ref=None) -> ExecutionEvent`.
- Consumes: existing `agent_control_plane.provenance.ProvenanceEvent` plus Task 1/2 contract types.

- [ ] **Step 1: Write failing tests** proving legacy event/task/run/capability/state/detail preservation, exact `unspecified` mapping for absent state, canonical UTC conversion, and fail-closed run mismatch.
- [ ] **Step 2: Push tests only and verify RED** for missing mapper behavior.
- [ ] **Step 3: Implement the mapper without fabricating trace/component/artifact/policy data.** Require supplied `monotonic_ns`; reject run mismatch with `ContractValidationError`.
- [ ] **Step 4: Push and verify GREEN** across the matrix.

### Task 4: Contract round-trip and evidence-boundary documentation

**Files:**
- Modify: `tests/test_contract.py`
- Modify: `src/agent_control_plane/contract/model.py`
- Modify: `docs/CONTROL_PLANE_KERNEL_SPEC.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `ExecutionEvent.from_dict()` (or equivalent explicit validator) that reconstructs the exact semantic contract from serialized data.

- [ ] **Step 1: Write failing round-trip test** from a fully populated serialized event back to an equal contract object; reject unsupported schema/version data during reconstruction.
- [ ] **Step 2: Push tests only and verify RED** for missing round-trip reconstruction.
- [ ] **Step 3: Implement minimal reconstruction/validation** reusing the same constructors rather than duplicating validation.
- [ ] **Step 4: Update README/kernel spec** to distinguish legacy provenance from the new execution contract and explicitly state that runtime portability, DGAF authorization, PDMAL efficacy, durability, attestation, and production readiness remain unestablished.
- [ ] **Step 5: Push and verify GREEN** across the complete matrix.

### Task 5: Final branch verification and review gate

**Files:** no new production scope.

- [ ] **Step 1: Compare branch against base `dbab7c1afafec524ce7c18157de2089cafe79c87`** and verify only planned contract/tests/docs changed.
- [ ] **Step 2: Verify exact-head GitHub Actions** across Python 3.10–3.14 with no failures.
- [ ] **Step 3: Re-read the design acceptance criteria** and classify each as VERIFIED, NOT VERIFIED, or NOT APPLICABLE from branch evidence.
- [ ] **Step 4: Open a PR only after exact-head verification is green.** PR text must preserve the evidence ceiling and state that portability remains NOT ESTABLISHED.
- [ ] **Step 5: Do not merge until PR-head checks are complete and no evidence-boundary regression is found.**
