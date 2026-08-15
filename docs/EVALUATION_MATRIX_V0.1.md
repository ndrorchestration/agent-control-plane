# ACP Evaluation Matrix v0.1

## Evidence boundary

This matrix evaluates the deterministic local kernel only. Passing these cases does not establish production reliability, distributed correctness, security effectiveness, autonomous behavior, or governance effectiveness.

| Case | Expected property | Evidence artifact |
|---|---|---|
| Successful dispatch | CREATED → RUNNING → COMPLETED | integration + evaluation tests |
| Handler failure | CREATED → RUNNING → FAILED | failure tests |
| Policy denial | no handler execution; task remains CREATED | policy tests |
| Unknown capability | reject without mutation | invariant/evaluation tests |
| Blank capability | registration rejected | adversarial tests |
| Terminal redispatch | rejected | invariant tests |
| Terminal recancellation | rejected | invariant tests |
| Cancellation | task becomes CANCELLED | invariant tests |
| Provenance ordering | deterministic event sequence | adversarial tests |
| Multi-task isolation | separate tasks produce separate ordered events | adversarial tests |

## Interpretation

A passing case establishes only the behavior represented by that test under the test environment. It does not generalize to workloads or operating conditions not represented here.

## Promotion criteria

ACP should not be promoted beyond local-kernel verification until the project has evidence for:

1. broader malformed-input coverage;
2. policy exception behavior;
3. persistence semantics, if persistence is introduced;
4. concurrency semantics, if concurrency is introduced;
5. measurable performance characteristics;
6. security/authentication controls;
7. integration behavior across real agent/tool boundaries.
