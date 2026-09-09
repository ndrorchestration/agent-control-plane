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

## Provenance

Each execution transition emits a structured `ProvenanceEvent` containing:

- event type;
- task identifier;
- capability when applicable;
- resulting state when applicable;
- optional failure or usage detail;
- UTC timestamp.

The event list is currently process-local and non-durable.

## Evidence boundary

The kernel and tests demonstrate local deterministic behavior only. The budget tests establish the cooperative count/cost accounting and fail-closed exhaustion properties exercised by those tests. They do not establish:

- production reliability;
- distributed correctness;
- security authorization;
- persistence guarantees;
- hard execution-time enforcement;
- provider-accurate token/cost metering;
- retry/checkpoint/delegation correctness;
- model quality;
- multi-agent coordination quality;
- governance effectiveness.

Those claims require separate implementation and empirical validation.
