# Agent Control Plane

**Agent Control Plane (ACP)** is an experimental control-plane kernel for coordinating, constraining, and observing AI-agent/workflow execution.

> **Epistemic status:** Experimental engineering. The repository contains an executable deterministic kernel with policy hooks, cooperative task budgets, and run-scoped provenance. It is not a complete autonomous control plane, security boundary, or production-ready orchestration platform.

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
- tests covering successful dispatch, handler failure, cancellation, policy decisions, adversarial/invariant cases, duplicate registration, unknown-capability evidence, provenance binding, exact-limit budget use, atomic overrun handling, and suppressed-exception fail-closure;
- GitHub Actions CI for the Python suite.

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
- a policy denial is recorded rather than treated as successful execution;
- an attempted cooperative resource-budget overrun becomes `BUDGET_EXHAUSTED` and cannot be converted into successful completion by catching the budget exception inside the handler.

These properties are local software invariants. They do not establish distributed reliability or system security.

## Not yet implemented / established

Unless added and independently verified later, ACP does **not** currently provide:

- model/provider integrations;
- automatic provider token/cost/tool-call metering;
- durable event or budget persistence;
- cryptographic/tamper-evident provenance;
- distributed execution;
- authentication or authorization infrastructure;
- bounded retry/backoff orchestration;
- execution deadlines/preemption for arbitrary handlers;
- checkpoint/resume with remaining-budget restoration;
- parent/child or delegated budget conservation;
- advanced scheduling;
- multi-process consistency;
- production reliability or security certification.

## Evidence standard

Claims in this repository should distinguish:

`DEFINED → IMPLEMENTED → COMPUTED → VERIFIED → ATTESTED → HISTORICAL → HYPOTHESIS → METAPHOR → UNSUPPORTED → DEPRECATED`

A passing unit test establishes only the tested property under that test environment. An exported provenance manifest is not an attestation. Cooperative resource accounting is not proof of externally measured consumption. Cross-repository use does not transfer validation.

## Ecosystem relationship

ACP may provide reusable primitives to other `ndrorchestration` projects. `DGAF-Framework`, PDMAL, Orbit-Driftwatch, Sentinel, and other repositories maintain separate evidence and governance boundaries. Integration should be demonstrated through explicit interfaces and tests.

## Current status

**Experimental / development track — executable kernel with run-scoped provenance, fail-closed dispatch invariants, and cooperative task-budget accounting.**

## Provenance

Maintained by Ndr / Ender Hensel (`ndrorchestration`).
