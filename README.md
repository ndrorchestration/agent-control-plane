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
- a transport-neutral `agent-control-plane.authority-sync.v0-candidate` contract for snapshot/revocation messages, per-sender replay sequencing, deterministic acknowledgements, duplicate detection, and explicit reconciliation rejection;\n- an additive SQLite-backed `agent-control-plane.authority-sync-log.v0-candidate` append-only reconciliation log that stores canonical applied messages, verifies content hashes on recovery, exposes a deterministic content-root identity, and can reconstruct authority state, revocations, duplicate detection, and sender replay sequence after process restart;\n- an `AuthoritySyncProgressGuard` that can hold the existing authority policy fail-closed until an explicitly configured sender-sequence floor has been reconciled locally, optionally combining that floor with the existing authority-state epoch/age requirement;\n- a transport-neutral `agent-control-plane.authority-sync-watermark.v0-candidate` record and trusted monotonic registry that lets explicitly trusted peers raise a required sequence floor for a target authority sender without allowing watermark regression;\n- an `AuthoritySyncWatermarkEndpoint` / `AuthoritySyncWatermarkTransport` boundary with canonical applied/duplicate acknowledgements and a deterministic loopback conformance adapter, keeping watermark trust semantics inside ACP rather than inside a network adapter;\n- an additive SQLite-backed `agent-control-plane.authority-sync-watermark-log.v0-candidate` durable watermark log that verifies canonical payload hashes and reconstructs accepted watermark floors across process restart;\n- a deterministic direct-peer convergence harness in which each peer may publish only the authority-sync sequence it has actually reconciled locally, allowing explicitly connected trusted peers to converge on the highest directly observed floor after partition/reconnect without re-originating third-party claims;\n- a bounded `agent-control-plane.authenticated-authority-sync-watermark.v0-candidate` HMAC-SHA256 envelope profile that binds the complete canonical watermark, issuer identity, key ID, algorithm, and schema to a 32-byte-or-longer caller-provisioned secret;\n- a non-secret `agent-control-plane.authority-sync-watermark-key.v0-candidate` lifecycle registry that enforces key activation windows, hard revocation, rotation metadata, and fail-closed unknown lifecycle state before cryptographic verification;\n- an optional `agent-control-plane.ed25519-authority-sync-watermark.v0-candidate` signature profile using public-key verification so downstream receivers can verify an origin watermark without receiving the origin signing secret;\n- a single-relay `agent-control-plane.authority-sync-watermark-relay.v0-candidate` envelope that carries the complete authenticated origin payload as base64 plus separate relay identity/time metadata, allowing the final receiver to bind the transport-authenticated relay identity and independently verify the origin before applying the watermark.\n- an experimental one-hop Reticulum relay adapter candidate that carries relay envelopes on a fixed request path, binds the declared relay ID to the Reticulum remote identity, and leaves embedded origin verification inside ACP; relay admission now has separate HMAC and Ed25519 origin-verification profiles behind the same byte-facing relay endpoint, while the live localhost gate still exercises the HMAC fixture path.\n- a transport-neutral `agent-control-plane.authority-sync-watermark-relay-chain.v0-candidate` Ed25519 profile that hash-links each signed relay hop to the immutable signed origin and prior hop, binds each hop to its declared next receiver, rejects relay loops, enforces a configured maximum hop count, and verifies relay-key lifecycle before accepting the chain.\n- a caller-provisioned `agent-control-plane.authority-key-binding.v0-candidate` registry that binds a logical subject/key ID to a SHA-256 public-key fingerprint and optionally to a transport-identity fingerprint, with activation windows and hard revocation; a bound Ed25519 verifier requires those bindings to match before signature verification.\n- a separate bounded localhost Reticulum topology candidate that routes canonical ACP authority-sync traffic through one transport-enabled intermediate Reticulum node, preserving end-to-end ACP sender identity at the destination.

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

Sync messages now also have a canonical UTF-8 JSON representation with sorted keys, compact separators, strict reconstruction, and SHA-256 content identity. Unknown message kinds, malformed UTF-8/JSON, wrong schemas, extra fields, malformed nested records, and unsupported nested values fail closed. The SHA-256 is a deterministic content identifier only; it is not a cryptographic signature, sender authentication, or tamper-evident transport by itself.\n\n`DurableAuthoritySyncReconciler` can persist only canonically `APPLIED` sync messages to an append-only SQLite log and recover process-local authority/revocation/replay state by replaying that durable prefix through the same canonical reconciler. Recovery verifies stored content hashes, canonical payload bytes, indexed message identity, and log schema before accepting state. Its `content_root_sha256` is a deterministic identity for the ordered stored-message set, not a signature, external attestation, secure key binding, consensus proof, or guarantee that storage itself cannot be maliciously rewritten.\n\nFor reconnect/recovery policy, `AuthoritySyncProgressGuard` can require a caller-supplied minimum reconciled sender sequence before the authority state is treated as current. It can now also consume a trusted `AuthoritySyncWatermarkRegistry`; configured peers may publish monotonic minimum-sequence observations for a target authority sender, and the guard uses the maximum accepted trusted floor. Missing dynamic watermark state fails closed. This prevents a node from treating a fresh snapshot as sufficient when a trusted peer reports that later sync records (for example a revocation) must also have arrived. Watermarks remain bounded observations, not proof of global completeness: ACP does not infer consensus, a globally latest sequence, or unknown missing messages. `DurableAuthoritySyncWatermarkRegistry` can preserve accepted watermark floors across process restart using an append-only canonical SQLite log with hash/index/schema verification; this is local durability evidence, not cryptographic attestation or protection against malicious storage rewrite. `AuthoritySyncWatermarkPublisher` derives a peer's emitted floor only from that peer's own reconciler progress, and the direct-peer convergence harness intentionally does not forward a third party's watermark as if it were locally observed. This preserves origin semantics while testing partition/reconnect convergence without pretending that relayed or multi-hop claims are solved. The authenticated-watermark profile adds a bounded symmetric-key integrity/authentication option. It detects changed watermark content, issuer identity, key identity, or signature under the configured key. It is not a public-key signature or non-repudiation mechanism: any party provisioned the same HMAC secret can forge a valid envelope. A future relay may therefore forward such an envelope opaquely without receiving the origin secret. The current single-relay admission candidate does exactly that: it requires the caller to supply the relay identity authenticated by the transport, checks that against the declared relay ID, then verifies the embedded origin envelope before applying the original watermark. This is one-hop provenance separation only; it does not establish arbitrary multi-hop relay, authenticated relay chains, key distribution, endpoint identity, liveness, or compromise resistance. `LifecycleAwareHmacWatermarkVerifier` adds a separate metadata gate for key activation windows, expiration, and hard revocation. Revocation is intentionally fail-closed for all future verification attempts, including envelopes issued before the revocation timestamp; ACP does not grandfather historical authenticated envelopes after a key is revoked. The optional Ed25519 profile uses the same lifecycle registry but replaces shared-secret verification with public-key verification. It requires the `crypto` extra and is separately CI-gated; it does not itself solve key distribution, certificate chains, hardware protection, or identity proofing.

`AuthoritySyncTransport` defines the adapter boundary: a transport exchanges canonical ACP bytes with a peer and returns canonical acknowledgement bytes. `AuthoritySyncEndpoint` retains decoding and reconciliation inside ACP, while `LoopbackAuthoritySyncTransport` provides an in-process conformance harness. Transport adapters must not redefine replay, authority-epoch, revocation, conflict, or acknowledgement semantics.

An experimental `ReticulumAuthoritySyncTransport` / `ReticulumAuthoritySyncServer` candidate maps that boundary onto Reticulum's documented `Link.request(...)` and `Destination.register_request_handler(...)` surfaces. A bounded localhost integration with `rns==1.5.4` has established snapshot/revocation exchange over a real Reticulum link; broader Reticulum/network compatibility remains NOT ESTABLISHED. The server can additionally bind claimed ACP sender IDs to identified Reticulum identity hashes. See [`docs/RETICULUM_ADAPTER.md`](docs/RETICULUM_ADAPTER.md).

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
