# ACP Kernel Specification v0.1

## Scope

This specification defines the minimum deterministic execution substrate currently implemented by Agent Control Plane.

## Task lifecycle

Allowed terminal states:

- `completed`
- `failed`
- `cancelled`

Dispatch is permitted only from `created`.

A successful handler execution produces `completed` and a result.
A handler exception produces `failed` and a string error record.
Cancellation is permitted from `created` or `running`.

## Routing

A capability name maps to exactly one registered handler in the in-memory kernel. Dispatch of an unknown capability is rejected.

This is local deterministic routing. It is **not** distributed scheduling, load balancing, service discovery, or autonomous agent selection.

## Policy boundary

Policy evaluation is represented as an explicit allow/deny decision with an optional reason. Policy is intentionally separated from execution so higher-level governance systems can supply policies without coupling them to the kernel.

## Provenance

Each execution transition emits a structured `ProvenanceEvent` containing:

- event type;
- task identifier;
- capability when applicable;
- resulting state when applicable;
- optional failure detail;
- UTC timestamp.

The event list is currently process-local and non-durable.

## Evidence boundary

The kernel and tests demonstrate local deterministic behavior only. They do not establish:

- production reliability;
- distributed correctness;
- security authorization;
- persistence guarantees;
- model quality;
- multi-agent coordination quality;
- governance effectiveness.

Those claims require separate implementation and empirical validation.
