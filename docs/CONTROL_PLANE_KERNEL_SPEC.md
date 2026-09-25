# ACP Kernel Specification v0.1

## Scope

This specification defines the minimum deterministic execution substrate currently implemented by Agent Control Plane.

## Task lifecycle

Allowed terminal states:

- `completed`
- `failed`
- `cancelled`
- `budget_exhausted`

Dispatch is permitted only from `created`.

A successful handler execution produces `completed` and a result.
A handler exception produces `failed` and a string error record.
Cancellation is permitted from `created` or `running`.
A declared cooperative resource-budget violation produces `budget_exhausted`, clears any handler result, and emits terminal provenance.

## Cooperative execution budgets

A `Task` may carry an `ExecutionBudget` with optional ceilings for:

- steps;
- tool calls;
- tokens;
- monetary cost.

Handlers and tool/runtime adapters account usage explicitly through `Task.consume(...)`. Charges are checked atomically before counters are updated. An attempted overrun raises `BudgetExceeded`; the task retains the violation as a sticky failure so a handler cannot catch the exception and then be recorded as successfully completed.

A successful completion records the task's reported resource usage in terminal provenance. A budget-exhausted task records both the violation and the last accepted usage totals.

This is **cooperative deterministic accounting**. It does not automatically observe provider token usage, tool calls, elapsed wall-clock time, or monetary cost unless the owning adapter reports them. It also does not preempt an arbitrary blocking handler.

Not yet implemented by this budget slice:

- hard wall-clock execution deadlines or preemption;
- bounded retry/backoff orchestration;
- checkpoint/resume with remaining-budget restoration;
- parent/child or delegated budget conservation;
- durable or distributed budget accounting.

## Routing

A capability name maps to exactly one registered handler in the in-memory kernel. Dispatch of an unknown capability is rejected.

This is local deterministic routing. It is **not** distributed scheduling, load balancing, service discovery, or autonomous agent selection.

## Policy boundary

Policy evaluation is represented as an explicit allow/deny decision with an optional reason. Policy is intentionally separated from execution so higher-level governance systems can supply policies without coupling them to the kernel.

The current kernel policy hook is a **pre-execution** allow/deny mechanism. The cross-runtime execution contract described below can carry an optional `policy_decision_ref`, but that field only associates an identified decision with an execution event. It does not add in-execution or post-execution policy engines and does not itself establish authorization.

## Provenance

Each kernel execution transition emits a structured `ProvenanceEvent` containing:

- event type;
- task identifier;
- run identifier;
- capability when applicable;
- resulting state when applicable;
- optional failure or usage detail;
- UTC timestamp.

`ControlPlane.provenance_manifest()` continues to export the existing `agent-control-plane.provenance.v1` representation. That manifest remains process-local and non-durable.

## Cross-runtime execution contract

ACP additionally defines a versioned framework-neutral execution/trace contract with schema identity:

`agent-control-plane.execution.v1`

The contract is additive to the existing kernel provenance representation. It currently provides immutable typed records for:

- `ExecutionIdentity` — explicit execution ID, run ID, and schema version;
- `TraceContext` — trace ID, span ID, and optional parent span ID;
- `ComponentIdentity` — component, component type, runtime, adapter, and optional source/version identity;
- `ArtifactRef` — artifact identity/type plus optional URI, version, and SHA-256 reference;
- `ExecutionEvent` — event type, execution/trace/component context, task/status, UTC timestamp, monotonic ordering value, optional capability/policy reference/artifacts/detail.

Required identity fields fail closed when blank. Unsupported schema versions, span self-parenting, malformed SHA-256 values, negative/non-integer monotonic values, and naive or non-UTC event timestamps are rejected with `ContractValidationError`.

Event timestamps serialize canonically in UTC with a trailing `Z`. Contract serialization is deterministic and `ExecutionEvent.from_dict()` reconstructs serialized events through the same validation paths, so malformed nested data does not bypass validation.

### Legacy provenance mapping

`map_provenance_event(...)` converts an existing `ProvenanceEvent` into an `ExecutionEvent` only when the caller supplies execution, trace, component, and monotonic context that the legacy event does not contain.

The mapper:

- preserves the legacy event type, task ID, capability, state, detail, and UTC timestamp;
- requires the legacy `run_id` to equal the supplied contract `run_id` and fails closed on mismatch;
- maps an absent legacy state to the explicit non-success placeholder `unspecified`;
- does not fabricate trace IDs, component IDs, artifacts, policy decisions, or successful status.

This mapper does not change `agent-control-plane.provenance.v1` and does not imply that historical events contained trace/span data they did not record.

### Current conformance boundary

The present contract tests establish ACP-native schema construction, validation, deterministic serialization, round-trip reconstruction, and legacy-provenance mapping under the tested Python environments.

They do **not** establish cross-runtime portability. No materially different external runtime adapter is implemented in this slice, and there is not yet a two-runtime conformance result using the same core schema without fork.

## Candidate authority envelope

ACP also contains a separate candidate authority record with schema identity:

`agent-control-plane.authority.v0-candidate`

The candidate represents:

- principal identity;
- requested capability;
- resource/target scope;
- operation/action semantics;
- policy identity plus version/hash;
- decision identity, explicit outcome, and reason code;
- authority lease expiry;
- optional delegation identity/scope;
- explicit authority conditions.

The record validates required identities, canonical UTC expiry, typed decision outcomes, non-empty unique delegation scope, and explicit conditions for conditional decisions. It can test lease validity at a caller-supplied UTC timestamp and fail closed at expiry.

This candidate is **not part of `agent-control-plane.execution.v1`**. ACP additionally provides a narrow `AuthorityPolicy` adapter over the existing pre-execution policy hook.

The adapter fails closed when authority is missing, malformed, capability-mismatched, expired, explicitly denied, or conditionally unresolved. Conditional authority requires an explicit caller-supplied evaluator; only a literal successful evaluation permits dispatch.

The adapter can additionally consult an optional revocation checker and delegation evaluator. Revocation is represented by an append-only in-memory registry with schema `agent-control-plane.revocation.v0-candidate`; a record applies at and after its canonical UTC revocation time. Delegated authority fails closed unless an explicit caller-supplied delegation evaluator returns literal `True`.

The adapter still does **not** authenticate identities, validate external policy authority or signatures, prove resource/operation scope legitimacy, cryptographically prove delegation legitimacy, provide durable/distributed revocation, persist leases, or bind authority records into execution-v1 events. Its allow/deny result is therefore a bounded local software decision, not proof of broader authorization validity.

### Authority decision evidence sidecar

`EvidenceAuthorityPolicy` wraps `AuthorityPolicy` without modifying the frozen kernel policy/provenance paths. Each policy evaluation can produce a process-local record with schema:

`agent-control-plane.authority-decision-evidence.v0-candidate`

The record binds task ID, run ID, capability, allow/deny result, denial reason, known authority/decision/policy identities, decision outcome/reason, observation time, and booleans showing whether revocation, delegation, and conditional checks were actually evaluated. The wrapper also exports a deterministic task-ID-sorted in-memory manifest.

This sidecar is **not** durable provenance, cryptographic attestation, execution-v1 integration, or independent proof that the referenced authority was legitimate. It records what the local authority policy evaluated and decided.

### Authority state freshness

ACP additionally provides an additive in-memory authority-state cache with schema:

`agent-control-plane.authority-state.v0-candidate`

Each snapshot binds an authority ID to a non-negative monotonic epoch, canonical UTC issuance time, and source ID. Cache updates fail closed on epoch regression and conflicting records at the same epoch.

A freshness requirement supplies both a minimum accepted epoch and a maximum snapshot age. Evaluation returns one of: `current`, `missing`, `stale_epoch`, `stale_age`, or `future_state`.

An optional `AuthorityPolicy` freshness checker can use this evaluation to block dispatch. Missing/stale/future state and checker errors fail closed. The authority decision evidence sidecar records whether a freshness check was performed and its stale-state reason when present.

This mechanism does **not** establish consensus, global ordering, Byzantine agreement, revocation propagation, network partition healing, or proof that the locally cached state is globally latest. It provides bounded local staleness detection suitable for later disconnected-runtime and Reticulum experiments.

## Evidence boundary

The kernel and tests demonstrate local deterministic behavior only. The budget tests establish the cooperative count/cost accounting and fail-closed exhaustion properties exercised by those tests. The execution-contract tests establish only the ACP-native contract properties exercised by those tests.

They do not establish:

- general cross-runtime portability;
- production reliability;
- distributed correctness;
- security authorization;
- DGAF authorization or governance effectiveness;
- PDMAL scientific validity or efficacy;
- persistence guarantees;
- durable or tamper-evident provenance;
- cryptographic attestation or custody independence;
- hard execution-time enforcement;
- provider-accurate token/cost metering;
- retry/checkpoint/delegation correctness;
- model quality;
- multi-agent coordination quality;
- superiority to existing orchestration standards or frameworks.

Those claims require separate implementation and evidence.
