# Agent Control Plane

**Agent Control Plane (ACP)** is the repository for experimental control-plane infrastructure for coordinating, evaluating, and observing AI-agent workflows.

> **Epistemic status:** Experimental engineering. This repository now contains a minimal executable control-plane kernel; it is not a claim of a complete autonomous control plane, governance system, or production-ready orchestration platform.

## Scope

The repository provides reusable control-plane components for:

- agent/task routing and orchestration;
- execution-state and lifecycle management;
- evaluation and verification hooks;
- provenance and observability;
- explicit policy/constraint decision hooks;
- integration points for multi-agent workflows.

The authoritative implementation status is the source tree, tests, CI results, and dated evaluation artifacts. Planned components are not described as implemented capabilities.

## Current implementation

The current kernel provides:

- `Task` — explicit task identity, payload, lifecycle state, result, and error;
- `ControlPlane` — capability registration, deterministic dispatch, lifecycle transitions, cancellation, and event recording;
- policy decision hooks — explicit allow/deny decisions with reasons;
- unit tests covering successful dispatch, failure conversion, unknown capabilities, cancellation, and policy decisions;
- GitHub Actions CI for the Python test suite.

This is intentionally small. Model/provider integrations, durable persistence, distributed execution, authentication/authorization, advanced scheduling, and production reliability controls remain future work unless independently implemented and verified.

## Quickstart

```python
from agent_control_plane import ControlPlane, Task

plane = ControlPlane()
plane.register("echo", lambda task: task.payload)

result = plane.dispatch("echo", Task(payload="hello"))
assert result.result == "hello"
```

Run the tests with:

```bash
python -m pip install -e . pytest
python -m pytest
```

## Terminology

- **ACP** — Agent Control Plane, the repository/project name used here.
- **DGAF** — Dynamic Governance Agentic Formation; a related but separate governance/evaluation research track.
- **PDMAL / PDMA-L** — Phi-Driven Multi-Agent Lattice; a separate lattice/control research track.

Shared terminology or integrations do not establish equivalence between these projects or validation of one by another.

## Epistemic standard

Claims in this repository should distinguish:

`DEFINED → IMPLEMENTED → COMPUTED → VERIFIED → ATTESTED → HISTORICAL → HYPOTHESIS → METAPHOR → UNSUPPORTED → DEPRECATED`

A design specification is not evidence of implementation. A passing unit test is not evidence of system-level reliability. A historical benchmark is not current validation without a reproducible run.

## Current status

**Experimental / development track — minimal executable kernel implemented.**

Before treating an orchestration or governance capability as production-ready, verify the exact implementation, test coverage, failure behavior, security controls, integration behavior, and current evaluation evidence.

## Relationship to the ecosystem

Agent Control Plane may serve as infrastructure for other ndrorchestration projects, but those relationships should be represented through explicit interfaces and integration tests rather than assumed from project names or shared concepts.

## Provenance

Developed by Ndr / Ender Hensel (`ndrorchestration`).
