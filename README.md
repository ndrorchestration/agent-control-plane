# Agent Control Plane

**Agent Control Plane (ACP)** is the repository for experimental control-plane infrastructure for coordinating, evaluating, and observing AI-agent workflows.

> **Epistemic status:** Experimental engineering. This README describes repository scope, not a claim that a complete autonomous control plane, governance system, or production-ready orchestration platform has been established.

## Scope

The repository is intended to contain reusable control-plane components for:

- agent/task routing and orchestration;
- execution-state and lifecycle management;
- evaluation and verification hooks;
- provenance and observability;
- policy or constraint enforcement where implemented;
- integration points for multi-agent workflows.

The authoritative implementation status is the source tree, tests, and dated evaluation artifacts. Planned components are not described as implemented capabilities.

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

**Experimental / development track.**

Before treating an orchestration or governance capability as production-ready, verify the exact implementation, test coverage, failure behavior, security controls, and current evaluation evidence.

## Relationship to the ecosystem

Agent Control Plane may serve as infrastructure for other ndrorchestration projects, but those relationships should be represented through explicit interfaces and integration tests rather than assumed from project names or shared concepts.

## Provenance

Developed by Ndr / Ender Hensel (`ndrorchestration`).
