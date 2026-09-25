# Agent Control Plane

**Agent Control Plane (ACP)** is an experimental control-plane kernel for coordinating, constraining, and observing AI-agent/workflow execution.

> **Epistemic status:** Experimental engineering. The repository contains an executable deterministic kernel with policy hooks, cooperative task budgets, run-scoped provenance, and an additive versioned framework-neutral execution/trace contract. It is not a complete autonomous control plane, security boundary, proven cross-runtime portability layer, or production-ready orchestration platform.

## Current implementation

The kernel currently provides:

- `Task` identity, payload, lifecycle state, result, and error;
- capability registration with duplicate-registration rejection;
- deterministic dispatch and lifecycle transitions;
- cancellation semantics;
- explicit policy allow/deny decisions;
- fail-closed rejection of unknown capabilities;
- optional cooperative `ExecutionBudget` ceilings for steps, tool calls, tokens, and cost;
- atomic resource accounting through `Task.consume(...)`;
- terminal `BUDGET_EXHAUSTED` behavior when a declared cooperative budget is exceeded, including protection against a handler suppressing `BudgetExceeded` and then completing successfully;
- run-scoped provenance events carrying both task ID and run ID;
- terminal provenance containing reported resource usage;
- a portable `agent-control-plane.provenance.v1` manifest for the current in-memory run;
- additive `agent-control-plane.execution.v1` contract types for execution, trace/span, component/runtime/adapter, artifact, and event identity;
- strict fail-closed validation of required identities, schema version, trace parentage, SHA-256 references, monotonic values, and UTC timestamps;
- deterministic execution-event serialization with canonical UTC `Z` timestamps and validated round-trip reconstruction;
- an explicit mapper from legacy `ProvenanceEvent` records into the new execution contract when the caller supplies context absent from legacy provenance;
- tests covering successful dispatch, handler failure, cancellation, policy decisions, adversarial/invariant cases, duplicate registration, unknown-capability evidence, provenance binding, exact-limit budget use, atomic overrun handling, suppressed-exception fail-closure, execution-contract validation/serialization, round-trip reconstruction, and provenance mapping;
- GitHub Actions CI for the Python suite;
- a separate candidate `agent-control-plane.authority.v0-candidate` typed authority envelope covering principal, capability, resource, operation, policy identity, decision outcome/reason, lease expiry, delegation scope, and explicit conditions;
- a fail-closed `AuthorityPolicy` adapter that can enforce envelope presence, capability binding, lease validity, explicit deny, caller-supplied conditional evaluation, revocation checks, and delegated-authority validation through the existing pre-execution policy hook. The envelope remains separate from `execution.v1`;
- an append-only in-memory `agent-control-plane.revocation.v0-candidate` registry with deterministic manifest output and time-scoped revocation checks;
- an additive `agent-control-plane.authority-decision-evidence.v0-candidate` sidecar that records run/task/capability plus authority, decision, policy, outcome, reason, observation time, and which state/revocation/delegation/condition checks were actually evaluated;
- a candidate `agent-control-plane.authority-state.v0-candidate` in-memory cache with monotonic authority epochs, source identity, snapshot time, maximum-age requirements, stale-epoch detection, stale-age detection, and future-state rejection for disconnected-node experiments;
- a transport-neutral `agent-control-plane.authority-sync.v0-candidate` contract for snapshot/revocation messages, per-sender replay sequencing, deterministic acknowledgements, duplicate detection, and explicit reconciliation rejection.

The legacy provenance manifest and the execution contract are distinct representations. `agent-control-plane.provenance.v1` remains unchanged and process-local. Mapping a legacy event into `agent-control-plane.execution.v1` requires caller-supplied execution/trace/component/monotonic context; ACP does not fabricate missing historical trace or identity data.

The provenance manifest is **an in-memory/exportable execution record**, not durable storage, tamper-evident attestation, or an external audit log. Resource accounting is **cooperative**: handlers or runtime/tool adapters must report usage with `Task.consume(...)`; the kernel does not infer provider token counts, tool usage, elapsed time, or cost automatically.

## Example

```python
from agent_control_plane import ControlPlane, ExecutionBudget, Task

plane = ControlPlane(run_id="example-run")

def echo(task):
    task.consume(steps=1, tokens=5)
    return task.payload

plane.register("echo", echo)

result = plane.dispatch(
    "echo",
    Task(
        payload="hello",
        budget=ExecutionBudget(max_steps=1, max_tokens=5),
    ),
)
assert result.result == "hello"

manifest = plane.provenance_manifest()
assert manifest["run_id"] == "example-run"
```

The versioned execution contract is available from the additive subpackage:

```python
from agent_control_plane.contract import (
    ComponentIdentity,
    ExecutionEvent,
    ExecutionIdentity,
    TraceContext,
)

identity = ExecutionIdentity(execution_id="exec-1", run_id="run-1")
trace = TraceContext(trace_id="trace-1", span_id="span-1")
component = ComponentIdentity(
    component_id="kernel",
    component_type="kernel",
    runtime_id="python",
    adapter_id="native-acp",
)

event = ExecutionEvent(
    event_type="task.completed",
    identity=identity,
    trace=trace,
    component=component,
    task_id="task-1",
    status="completed",
    utc_timestamp="2026-09-14T23:00:00Z",
    monotonic_ns=1,
)
assert ExecutionEvent.from_dict(event.to_dict()) == event
```

Run verification with:

```bash
python -m pip install -e . pytest
python -m pytest
```

## Fail-closed boundaries

The current kernel and contract deliberately reject or record several ambiguous states:

- an empty capability cannot be registered;
- an already registered capability cannot be silently replaced;
- a terminal task cannot be redispatched;
- an unknown capability produces a provenance rejection event and raises `KeyError`;
- a handler exception becomes a recorded `FAILED` task state;
- a policy denial is recorded rather than treated as successful execution;
- an attempted cooperative resource-budget overrun becomes `BUDGET_EXHAUSTED` and cannot be converted into successful completion by catching the budget exception inside the handler;
- blank required execution/trace/component/artifact identity is rejected;
- unsupported execution-contract schema versions are rejected;
- trace span self-parenting is rejected;
- malformed optional SHA-256 references are rejected;
- negative or non-integer monotonic values are rejected;
- naive or non-UTC event timestamps are rejected;
- legacy provenance cannot be mapped across a mismatched run identity;
- absent legacy state maps to explicit `unspecified`, never inferred success.

These properties are local software invariants under the tested conditions. They do not establish distributed reliability, system security, governance efficacy, or cross-runtime portability.

## Not yet implemented / established

Unless added and independently verified later, ACP does **not** currently provide:

- materially different external runtime adapters conforming to `agent-control-plane.execution.v1`;
- two-runtime portability evidence without core-schema fork;
- model/provider integrations;
- automatic provider token/cost/tool-call metering;
- durable event, trace, or budget persistence;
- cryptographic/tamper-evident provenance;
- distributed execution;
- kernel-enforced authentication or authorization infrastructure;
- bounded retry/backoff orchestration;
- execution deadlines/preemption for arbitrary handlers;
- checkpoint/resume with remaining-budget restoration;
- parent/child or delegated budget conservation;
- advanced scheduling;
- multi-process consistency;
- production reliability or security certification.

## Authority candidate boundary

The candidate authority envelope is an **engineering primitive**, not an authorization system. It provides typed, fail-closed records and explicit lease-expiry checks using caller-supplied UTC time.

It does not authenticate principals, verify policy signatures, establish delegation legitimacy, revoke authority, persist leases, or bind an authority envelope to an execution event. `AuthorityPolicy` can now deny or permit the existing dispatch path for a narrow locally checkable subset, including optional revocation and delegation checks. Revocation state is currently process-local/in-memory, and delegation legitimacy remains caller-supplied rather than cryptographically established. Resource/operation legitimacy, identity authenticity, durable revocation, and cryptographic policy authority remain separate gates.

The candidate is intentionally separate from frozen `agent-control-plane.execution.v1` so GSAE-E0 Stage-A can measure that contract without the measurement target being silently repaired first.

`EvidenceAuthorityPolicy` can wrap `AuthorityPolicy` and retain one structured decision-evidence record per task. This creates an explicit local linkage between an ACP task/run and the authority decision used by the pre-execution policy path without modifying frozen kernel/provenance/contract files. The evidence sidecar is process-local, mutable in memory, non-cryptographic, and not an external audit log.

For disconnected/stale-state experiments, `InMemoryAuthorityStateCache` tracks a monotonic epoch and issuance time per authority. An optional policy freshness checker can require a minimum epoch and maximum snapshot age. Missing state, epoch regression, same-epoch conflict, stale epoch, stale age, future-dated state, or checker failure are fail-closed conditions. This is a local staleness control, not distributed consensus or proof that a node has received the globally newest state.

A deterministic synthetic partition harness under `experiments/authority_partition/` exercises divergent node caches, age-out during isolation, reconciliation to a newer epoch, and missing-state fail-closure. It is explicitly not a Reticulum/network simulation; it provides a local pre-integration test surface for those semantics.

The authority-sync candidate is transport-neutral. Transport sequence numbers provide replay/order protection per sender; authority-state epochs independently express the semantic version of authority state. A higher transport sequence cannot override a lower authority epoch, and a valid authority epoch does not excuse a replayed transport message. Snapshot/revocation application produces explicit applied/duplicate/rejected acknowledgements rather than silent reconciliation.

## Evidence standard

Claims in this repository should distinguish:

`DEFINED → IMPLEMENTED → COMPUTED → VERIFIED → ATTESTED → HISTORICAL → HYPOTHESIS → METAPHOR → UNSUPPORTED → DEPRECATED`

A passing unit test establishes only the tested property under that test environment. An exported provenance manifest is not an attestation. Cooperative resource accounting is not proof of externally measured consumption. ACP-native execution-contract conformance is not proof of cross-runtime portability. Cross-repository use does not transfer validation.

## Ecosystem relationship

ACP is the preferred experimental implementation host for a framework-neutral execution contract. DGAF retains governance, authorization, provenance/evidence-discipline, and evidence-state authority. PDMAL is a governed empirical workload/research consumer rather than a prerequisite parent of ACP. Other `ndrorchestration` repositories maintain separate evidence boundaries.

A framework/runtime adapter may populate the ACP execution contract, but adapter readiness, CI success, deployment health, or successful execution cannot self-promote DGAF authorization, PDMAL scientific validity, empirical efficacy, or general portability.

## Current status

**Experimental / development track — executable kernel with run-scoped provenance, fail-closed dispatch invariants, cooperative task-budget accounting, and an ACP-native versioned execution/trace contract with deterministic serialization and validation. Cross-runtime portability remains NOT ESTABLISHED.**

## Provenance

Maintained by Ndr / Ender Hensel (`ndrorchestration`).
