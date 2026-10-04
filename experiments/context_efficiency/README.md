# CEP Baseline / Comparison Lane

Status: **candidate experiment plumbing only**

This lane exists to freeze baseline observations before any context-efficiency
treatment is introduced.

## Sequence

1. Construct the exact task `ContextState`.
2. Record passive `ContextTelemetry`.
3. Store a `BaselineObservation`.
4. Compute its canonical SHA-256 identity.
5. Create a `ComparisonPlan` that binds to that baseline identity.
6. Only then implement/run the treatment.
7. Compare the treatment against the frozen control without changing the task
   contract or preservation checks.

## First proposed treatment

**Capability-driven tool gating**: resolve a task to the smallest relevant
capability/tool family before exposing tool schemas.

This README does not authorize or implement tool gating. It preregisters the
shape of a future comparison only.

Primary candidate metric:
- `tool_definitions_exposed`

Required preservation checks:
- same task contract;
- same explicit authority/claim boundaries;
- same canonical evidence references required for the decision;
- no hidden authority transfer;
- no material acceptance/correctness regression.

No baseline numbers are entered until they are directly observed.

Claim ceiling remains unchanged:
- `SCIENTIFIC_N_INCREMENT=0`
- `INDEPENDENT_VALIDATION=NOT_ESTABLISHED`
- `CANONICAL_DGAF_EFFICACY=NOT_ESTABLISHED`
- `HIGH_ASSURANCE=NOT_AUTHORIZED`
