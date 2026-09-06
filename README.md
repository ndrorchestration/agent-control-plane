# Agent Control Plane

**Agent Control Plane (ACP)** is an experimental control-plane kernel for coordinating, constraining, and observing AI-agent/workflow execution.

> **Epistemic status:** Experimental engineering. The repository contains an executable deterministic kernel with policy hooks and run-scoped provenance. It is not a complete autonomous control plane, security boundary, or production-ready orchestration platform.

## Current implementation

The kernel currently provides:

- `Task` identity, payload, lifecycle state, result, and error;
- capability registration with duplicate-registration rejection;
- deterministic dispatch and lifecycle transitions;
- cancellation semantics;
- explicit policy allow/deny decisions;
- fail-closed rejection of unknown capabilities;
- run-scoped provenance events carrying both task ID and run ID;
- a portable `agent-control-plane.provenance.v1` manifest for the current in-memory run;
- tests covering successful dispatch, handler failure, cancellation, policy decisions, adversarial/invariant cases, duplicate registration, unknown-capability evidence, and provenance binding;
- GitHub Actions CI for the Python suite.

The provenance manifest is **an in-memory/exportable execution record**, not durable storage, tamper-evident attestation, or an external audit log.

## Example

```python
from agent_control_plane import ControlPlane, Task

plane = ControlPlane(run_id="example-run")
plane.register("echo", lambda task: task.payload)

result = plane.dispatch("echo", Task(payload="hello"))
assert result.result == "hello"

manifest = plane.provenance_manifest()
assert manifest["run_id"] == "example-run"
```

Run verification with:

```bash
python -m pip install -e . pytest
python -m pytest
```

## Fail-closed boundaries

The current kernel deliberately rejects or records several ambiguous states:

- an empty capability cannot be registered;
- an already registered capability cannot be silently replaced;
- a terminal task cannot be redispatched;
- an unknown capability produces a provenance rejection event and raises `KeyError`;
- a handler exception becomes a recorded `FAILED` task state;
- a policy denial is recorded rather than treated as successful execution.

These properties are local software invariants. They do not establish distributed reliability or system security.

## Not yet implemented / established

Unless added and independently verified later, ACP does **not** currently provide:

- model/provider integrations;
- durable event persistence;
- cryptographic/tamper-evident provenance;
- distributed execution;
- authentication or authorization infrastructure;
- bounded retry/backoff orchestration;
- execution deadlines/preemption for arbitrary handlers;
- advanced scheduling;
- multi-process consistency;
- production reliability or security certification.

## Evidence standard

Claims in this repository should distinguish:

`DEFINED → IMPLEMENTED → COMPUTED → VERIFIED → ATTESTED → HISTORICAL → HYPOTHESIS → METAPHOR → UNSUPPORTED → DEPRECATED`

A passing unit test establishes only the tested property under that test environment. An exported provenance manifest is not an attestation. Cross-repository use does not transfer validation.

## Ecosystem relationship

ACP may provide reusable primitives to other `ndrorchestration` projects. `DGAF-Framework`, PDMAL, Orbit-Driftwatch, Sentinel, and other repositories maintain separate evidence and governance boundaries. Integration should be demonstrated through explicit interfaces and tests.

## Current status

**Experimental / development track — executable kernel with run-scoped provenance and fail-closed dispatch invariants.**

## Provenance

Maintained by Ndr / Ender Hensel (`ndrorchestration`).
