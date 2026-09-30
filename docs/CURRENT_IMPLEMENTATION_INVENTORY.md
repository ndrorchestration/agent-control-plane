# Current Implementation Inventory

This page is the intentionally detailed engineering inventory for ACP. The public README is the front door; this document is the deeper implementation ledger.

## Status

ACP is experimental engineering infrastructure. The inventory below describes local software primitives and candidates under bounded test conditions. It does not establish production readiness, security certification, distributed reliability, independent validation, or governance efficacy.

## Core kernel

Current ACP implementation work includes:

- task identity, payload, lifecycle state, result, and error;
- capability registration with duplicate-registration rejection;
- deterministic dispatch and lifecycle transitions;
- cancellation semantics;
- explicit policy allow/deny decisions;
- fail-closed rejection of unknown capabilities;
- cooperative `ExecutionBudget` ceilings for reported steps, tool calls, tokens, and cost;
- atomic resource accounting through `Task.consume(...)`;
- terminal `BUDGET_EXHAUSTED` behavior when declared cooperative budgets are exceeded;
- run-scoped provenance events carrying task ID and run ID;
- terminal provenance containing reported resource usage;
- portable `agent-control-plane.provenance.v1` manifest for the current in-memory run;
- additive `agent-control-plane.execution.v1` contract types for execution, trace/span, component/runtime/adapter, artifact, and event identity;
- strict fail-closed validation of required identities, schema version, trace parentage, SHA-256 references, monotonic values, and UTC timestamps;
- deterministic execution-event serialization with canonical UTC `Z` timestamps and validated round-trip reconstruction;
- an explicit mapper from legacy `ProvenanceEvent` records into the newer execution contract when the caller supplies context absent from legacy provenance.

## Authority and provenance candidates

ACP also contains bounded candidates for:

- typed authority envelopes;
- authority policy admission;
- revocation registry behavior;
- authority-decision evidence sidecars;
- authority-state cache behavior;
- authority sync, reconciliation, watermark, relay, and key-binding profiles;
- HMAC and Ed25519 verification candidates;
- relay-chain composition and verification;
- Reticulum-related relay experiments under local bounded conditions.

These candidates are engineering primitives, not a deployed authorization system or network security boundary.

## Supervisor and process-control candidates

ACP contains bounded supervisor/process candidates for:

- relay forward queues;
- retry/dead-letter handling;
- process supervision decisions;
- admitted managed-process launch;
- scheduled monitor ticks;
- bounded and gated supervisor runners;
- ownership leases and fencing;
- generation-fenced runtime checkpoints;
- recovery-admission and recovery-authorization records.

These candidates are designed to make service-control state explicit and fail closed. They do not imply an autonomous production daemon or unattended operation guarantee.

## Evidence interpretation

The useful public claim is:

> ACP demonstrates tested local control-plane primitives for bounded execution, explicit admission decisions, provenance records, authority-envelope candidates, and fail-closed supervision patterns.

Do not inflate this into claims of:

- production readiness;
- security certification;
- distributed reliability;
- autonomous orchestration;
- independent validation;
- governance efficacy.

## Historical note

The previous README contained a long inline inventory of many candidate primitives. That material has been compressed here to keep the repository front page readable while preserving the distinction between implemented local primitives, candidates, experiments, and unestablished claims.
