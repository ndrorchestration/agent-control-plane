# Cross-Runtime Execution Contract v1 — Design

**Status:** Design candidate for implementation in `agent-control-plane`. This document does not establish contract acceptance, portability, production readiness, DGAF authorization, PDMAL empirical validity, or efficacy.

## Purpose

Add a versioned, framework-neutral execution/trace contract alongside the existing Agent Control Plane kernel so heterogeneous runtimes can emit and consume the same execution identity, trace, event, artifact, policy, and evidence metadata without making any runtime framework authoritative over the core ontology.

The change is additive. Existing `Task`, `ControlPlane`, cooperative budget behavior, and `agent-control-plane.provenance.v1` remain compatible during this slice.

## Architecture boundary

- **DGAF** owns governance, authorization, evidence-state transitions, and fail-closed policy authority.
- **agent-control-plane (ACP)** is the preferred implementation host for the framework-neutral execution contract and future runtime adapters.
- **PDMAL** is a governed empirical workload/research consumer. It does not define the ACP contract and is not a prerequisite parent of ACP.
- **Metasymphony** may name a composed execution profile using the contract. It is not a separate framework or control plane by default.
- **Evaluators** such as Axiom Lens or provenance-regression tooling attach through explicit bounded interfaces. They do not mutate the core schema merely because they exist.

## Design principles

1. **Framework neutrality:** LangGraph, Microsoft Agent Framework, MCP, A2A, OpenAI runtimes, Hermes, PDMAL-specific runtimes, and future systems are adapters or consumers, not schema authorities.
2. **Additive compatibility:** do not rewrite the existing kernel to introduce the contract. Existing behavior remains valid while the new contract is introduced and mapped.
3. **Typed identity before adapter work:** establish execution, trace, span, actor/component, runtime/adapter, artifact, and schema identity before building external adapters.
4. **Deterministic serialization:** contract objects must serialize deterministically for fixtures, hashing, comparison, and evidence binding.
5. **Fail closed on malformed identity:** blank or structurally invalid required identifiers and unsupported schema versions are rejected rather than normalized silently.
6. **Evidence separation:** contract conformance is engineering evidence. It is not runtime portability, governance authorization, empirical efficacy, or scientific validation.
7. **No hidden ontology fork:** runtime adapters may populate contract fields but may not silently redefine required semantics.

## Scope of this implementation slice

### In scope

- a versioned contract module/package;
- execution identity;
- trace/span context;
- actor/component and runtime/adapter identity;
- artifact references with optional version/hash metadata;
- versioned execution-event objects;
- UTC timestamp plus monotonic ordering/timing field semantics;
- execution status/event classification;
- optional policy-decision reference;
- deterministic `to_dict` / JSON-ready serialization;
- strict construction/validation for required fields;
- mapping from current ACP provenance events into the new contract without removing `agent-control-plane.provenance.v1`;
- deterministic contract/conformance fixtures and tests;
- documentation of evidence boundaries and unsupported claims.

### Explicitly out of scope

- LangGraph, Microsoft Agent Framework, MCP, A2A, OpenAI, Hermes, or PDMAL adapter implementation;
- two-runtime portability claims;
- durable persistence or distributed trace storage;
- cryptographic/tamper-evident provenance;
- provider-accurate metering;
- hard deadline/preemption;
- checkpoint/resume;
- delegated-budget conservation;
- authentication or authorization infrastructure;
- empirical DGAF/PDMAL runs;
- semantic/embedding evaluators;
- changes to DGAF governance state.

## Contract structure

The first implementation should use a focused module or package under `src/agent_control_plane/contract/`. Exact internal file decomposition may be adjusted to fit repository conventions, but public concepts and semantics below are normative for this slice.

### `ExecutionIdentity`

Required fields:

- `execution_id: str` — stable identifier for one logical execution;
- `run_id: str` — ACP/run-level identity;
- `schema_version: str` — exact contract version, initially `agent-control-plane.execution.v1`.

Validation:

- all required identifiers must be non-empty after trimming;
- unsupported schema versions fail closed;
- identifiers are preserved exactly after validation; they are not silently regenerated.

`execution_id` is intentionally distinct from existing `task_id` and `run_id`: a task is a kernel object, a run scopes ACP provenance, and an execution is the cross-runtime unit represented by this contract.

### `TraceContext`

Required fields:

- `trace_id: str`;
- `span_id: str`.

Optional field:

- `parent_span_id: str | None`.

Validation:

- `trace_id` and `span_id` must be non-empty;
- when present, `parent_span_id` must be non-empty;
- `span_id` must not equal `parent_span_id`;
- this slice does not prescribe UUID, W3C Trace Context, or OpenTelemetry formatting. Format standardization may be added later through an explicit compatibility decision.

### `ComponentIdentity`

Required fields:

- `component_id: str` — stable actor/tool/agent/service/component identifier;
- `component_type: str` — bounded descriptive type such as `kernel`, `agent`, `tool`, `runtime`, or `evaluator`;
- `runtime_id: str` — runtime/execution environment identity;
- `adapter_id: str` — adapter identity, including `native-acp` for the current kernel mapping.

Optional fields:

- `version: str | None`;
- `source_ref: str | None` — commit/build/package/deployment identity where material.

No named persona is required by the contract. Persona presentation or historical actor lineage belongs outside this primitive identity layer unless represented as ordinary metadata by a higher-level profile.

### `ArtifactRef`

Required fields:

- `artifact_id: str`;
- `kind: str`.

Optional fields:

- `uri: str | None`;
- `version: str | None`;
- `sha256: str | None`.

Validation:

- required fields must be non-empty;
- if `sha256` is present it must be 64 lowercase hexadecimal characters;
- the contract does not claim that a hash proves custody, attestation, or independence.

### `ExecutionEvent`

Required fields:

- `event_type: str`;
- `identity: ExecutionIdentity`;
- `trace: TraceContext`;
- `component: ComponentIdentity`;
- `task_id: str`;
- `status: str`;
- `utc_timestamp: str`;
- `monotonic_ns: int`.

Optional fields:

- `capability: str | None`;
- `policy_decision_ref: str | None`;
- `input_artifacts: tuple[ArtifactRef, ...]`;
- `output_artifacts: tuple[ArtifactRef, ...]`;
- `detail: str | None`.

Validation:

- required strings must be non-empty;
- `monotonic_ns` must be an integer >= 0;
- `utc_timestamp` must be timezone-aware ISO-8601 UTC and normalized to a `Z` or `+00:00` representation chosen consistently by implementation;
- artifact arrays preserve caller order;
- serialization emits stable field names and deterministic nested ordering.

## Event mapping from current ACP provenance

The current `ProvenanceEvent` remains supported. The additive mapper converts an existing provenance event to `ExecutionEvent` when the caller supplies the cross-runtime context not present in v1 provenance:

- `ExecutionIdentity`;
- `TraceContext`;
- `ComponentIdentity`;
- optional artifact references and policy-decision reference.

Mapping rules:

- existing `ProvenanceEvent.event` -> `ExecutionEvent.event_type`;
- existing `task_id` -> `task_id`;
- existing `run_id` must equal `ExecutionIdentity.run_id`; mismatch fails closed;
- existing `capability` -> `capability`;
- existing `state` -> `status`; when state is absent the mapper uses an explicit non-success placeholder such as `unspecified`, never inferred success;
- existing `detail` -> `detail`;
- existing UTC timestamp -> `utc_timestamp` after strict validation;
- `monotonic_ns` must be supplied by the mapping call or event-emission boundary; it is not reconstructed from wall-clock time.

The mapper must not fabricate trace IDs, component IDs, source refs, artifacts, policy decisions, or successful status from missing historical data.

## Policy lifecycle boundary

This slice records a `policy_decision_ref` but does not implement new in-execution or post-execution policy engines.

The current ACP policy hook remains a pre-execution allow/deny mechanism. Future policy phases must be separately designed and tested. A recorded policy reference means only that an identified policy decision is associated with an event; it does not prove authorization unless DGAF or another governing authority establishes that relationship.

## Serialization and conformance

Contract objects expose deterministic JSON-ready dictionaries. The implementation must not include process addresses, unordered set output, generated timestamps at serialization time, or other nondeterministic fields.

A conformance fixture should serialize a fully populated event to an exact expected dictionary. A second round-trip test should reconstruct or validate the same contract data without semantic drift.

This first suite establishes **schema/serialization conformance for ACP-native events only**. It is not a cross-runtime portability suite until a materially different adapter is implemented and executes the same fixtures.

## Error handling

Construction or conversion must raise explicit validation errors for:

- blank required identity fields;
- unsupported schema version;
- blank parent span when provided;
- span self-parenting;
- malformed artifact SHA-256;
- negative monotonic value;
- non-UTC or naive event timestamps;
- `run_id` mismatch during provenance mapping.

No invalid required value may be replaced automatically with a generated identifier.

## Compatibility

The existing public imports and current kernel behavior remain unchanged in this slice.

`agent-control-plane.provenance.v1` remains exportable. The new contract is an additional representation and does not silently change the manifest schema.

A later explicit migration may version the provenance manifest to include execution/trace data after conformance evidence exists. That migration is outside this design.

## Test strategy

Use TDD for each behavior. The minimum tests are:

1. valid execution identity construction and deterministic serialization;
2. blank/unsupported identity rejection;
3. valid trace construction;
4. blank trace ID/span ID and self-parent rejection;
5. component identity serialization without persona dependence;
6. artifact hash validation;
7. deterministic full event serialization;
8. rejection of negative monotonic values;
9. rejection of naive/non-UTC timestamps;
10. provenance-to-contract mapping preserves event/task/run/capability/state/detail;
11. provenance mapping rejects run mismatch;
12. provenance mapping does not infer success when source state is absent;
13. existing ACP test suite remains green without public-behavior changes.

Tests must assert real behavior, not implementation-specific mocks.

## Acceptance criteria for this slice

This design slice may be described as implemented only when:

- the contract types and validation rules exist in source;
- required TDD red/green evidence has been observed during implementation;
- deterministic serialization tests pass;
- current provenance can be mapped without modifying the existing manifest schema;
- the full existing test suite passes;
- CI passes on the exact implementation head;
- documentation states that portability and empirical efficacy remain not established.

Even after those criteria pass, the ADR remains a candidate until its broader acceptance gate is met, including materially different adapters using the same core schema without fork.

## Follow-on sequence

After this slice is accepted:

1. define a minimal adapter protocol that consumes/emits the stable contract;
2. implement one ACP-native reference adapter if a distinct adapter surface is still needed;
3. implement one materially different external/runtime adapter;
4. run the same conformance fixtures across both;
5. only then evaluate a portability claim;
6. separately design in-execution/post-execution policy phases, evaluator attachment, persistence, and advanced bounded-execution capabilities as evidence justifies them.

## Evidence ceiling

The strongest claim this slice can support is:

> ACP implements and tests a versioned framework-neutral execution/trace contract for its native kernel representation, with deterministic serialization and fail-closed validation under the tested conditions.

It cannot establish:

- general runtime portability;
- DGAF authorization;
- PDMAL efficacy;
- secure or tamper-evident provenance;
- distributed reliability;
- production readiness;
- superiority to existing orchestration standards or frameworks.
