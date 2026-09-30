# Agent Control Plane

**Agent Control Plane (ACP)** is an experimental Python control-plane kernel for bounded agent and workflow execution. It focuses on deterministic dispatch, fail-closed policy checks, cooperative resource budgets, provenance records, authority-envelope candidates, and bounded supervisor/service-control candidates.

> **Status:** experimental engineering. ACP is not a production orchestrator, security boundary, autonomous agent runtime, distributed control plane, or independently validated governance system.

## What this repository is for

ACP explores the control-plane layer around agentic work:

- what task is being run;
- which capability is being invoked;
- whether policy admits or denies execution;
- what budget or authority envelope applies;
- what provenance record is emitted;
- what happens when execution, replay, relay, or supervision should fail closed.

The repository is intended as implementation evidence and design research for the broader `ndrorchestration` governance ecosystem. It is written to make boundaries explicit rather than to imply production readiness.

## Current implemented surface

The current Python package includes tested local primitives for:

- task identity, lifecycle state, result, and error handling;
- capability registration and duplicate-registration rejection;
- deterministic dispatch and cancellation semantics;
- explicit policy allow/deny decisions;
- fail-closed rejection of unknown capabilities;
- cooperative execution budgets for reported steps, tool calls, tokens, and cost;
- run-scoped provenance manifests;
- additive execution-contract types for execution, trace/span, component/runtime/adapter, artifact, and event identity;
- authority-envelope, revocation, authority-state, sync, watermark, relay, and supervisor candidates under bounded test conditions.

For the full development inventory and candidate list, see [`docs/CURRENT_IMPLEMENTATION_INVENTORY.md`](docs/CURRENT_IMPLEMENTATION_INVENTORY.md).

## What is not established

Unless separately implemented and verified later, ACP does **not** currently establish:

- production reliability;
- security certification;
- independent validation;
- distributed-system reliability;
- model/provider integration;
- automatic provider token, tool-call, cost, or latency metering;
- durable external audit logging;
- tamper-evident provenance;
- autonomous background operation;
- cross-runtime portability evidence;
- governance efficacy.

Local invariants and tests are valuable engineering evidence, but they should not be read as proof of production safety, security, or real-world governance effectiveness.

## Quick example

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
assert plane.provenance_manifest()["run_id"] == "example-run"
```

## Run verification

```bash
python -m pip install -e . pytest
python -m pytest
```

## Documentation map

| Document | Purpose |
|---|---|
| [`docs/CONTROL_PLANE_KERNEL_SPEC.md`](docs/CONTROL_PLANE_KERNEL_SPEC.md) | Core kernel design and behavior. |
| [`docs/CURRENT_IMPLEMENTATION_INVENTORY.md`](docs/CURRENT_IMPLEMENTATION_INVENTORY.md) | Detailed implementation/candidate inventory. |
| [`docs/PUBLIC_SURFACE_REVIEW.md`](docs/PUBLIC_SURFACE_REVIEW.md) | Public-facing review checklist and repo metadata guidance. |
| [`docs/LONG_RUNNING_SUPERVISOR_DESIGN_GATE.md`](docs/LONG_RUNNING_SUPERVISOR_DESIGN_GATE.md) | Supervisor design gate and non-production boundaries. |
| [`docs/REMOTE_DESKTOP_COMMANDER_ADAPTER.md`](docs/REMOTE_DESKTOP_COMMANDER_ADAPTER.md) | Experimental adapter notes requiring public-surface review before promotion. |
| [`docs/REMOTE_MUTATION_ADMISSION.md`](docs/REMOTE_MUTATION_ADMISSION.md) | Remote mutation admission notes requiring careful authority framing. |
| [`docs/RELEASE_AND_EVIDENCE_POLICY.md`](docs/RELEASE_AND_EVIDENCE_POLICY.md) | Release and evidence policy. |

## Suggested GitHub About description

The repository About field should be set manually to:

> Experimental control-plane kernel for bounded agent execution, policy checks, provenance, authority envelopes, and fail-closed workflow supervision.

## Suggested topics

```text
agent-control-plane
ai-governance
agentic-ai
workflow-governance
provenance
authority-model
fail-closed
python
multi-agent-systems
experimental
```

## Public-facing boundary

This repository is intentionally public as a design and implementation artifact. Deep design notes, experiments, and frontier documents may be technical and provisional; they are evidence of development work, not product claims.

Before using ACP in public claims, keep the distinction between:

- implemented local software invariants;
- candidate contracts and experiments;
- documented design boundaries;
- unestablished production, security, distributed, or independent-validation claims.

## License

Apache-2.0.
