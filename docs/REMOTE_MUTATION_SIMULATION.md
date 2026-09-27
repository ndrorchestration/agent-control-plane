# Remote Mutation Simulation Composition

Status: **SIMULATION ONLY / NO LIVE SIDE EFFECT / NO RDC MUTATION**.

This tranche composes the canonical draft mutation-control stack through #108
without mutating a repository and without calling Remote Desktop Commander.

## Purpose

Exercise the required ordering and evidence relationships before any live
executor is considered:

1. start from an already-issued exact single-use authorization;
2. validate simulation chronology and rollback-described prestate;
3. consume authorization before any modeled effect;
4. durably record execution intent;
5. apply the typed mutation only to an in-memory byte mapping;
6. record a simulated external-effect hash;
7. derive a simulation-scoped postcondition record;
8. record verified postcondition evidence;
9. bind result/effect/postcondition evidence;
10. close the consumed authorization against the terminal evidence chain.

## Simulation namespace

To prevent evidence laundering, durable simulation identities must use the
`simulation:` namespace:

- authorization ID;
- transaction ID;
- executor ID;
- execution ID.

The returned result also fixes:

```text
simulation_only=true
live_side_effect_performed=false
acp_mutation_executed=false
```

A simulation artifact is never live-execution evidence.

## Pre-effect checks

Before authorization consumption the simulator checks:

- exact authorization/plan identity;
- journal is `PREPARED`;
- UTC chronology;
- rollback descriptor SHA-256 matches plan + authorization;
- rollback descriptor operation/path matches the plan;
- simulated prestate uses byte values only;
- restore-file rollback requires the target to exist with exact prior hash/size;
- delete-created-file rollback requires the target to be absent.

A failed pre-effect check does not consume the authorization.

## Ambiguous interruption

The harness can stop immediately after authorization consumption and durable
execution-intent recording.

That outcome:

- applies no simulated effect;
- creates no success evidence;
- leaves the journal in the canonical ambiguous-effect recovery hold;
- requires a fresh authorization for any later attempt.

## Boundaries

This tranche does **not**:

- write, delete, rename, or create any repository file;
- call Remote Desktop Commander;
- authenticate a real executor;
- prove causality;
- execute rollback;
- authorize recovery;
- establish production security;
- establish live mutation capability.

The next gate after this simulation is not automatically a live executor. The
simulation must first survive adversarial/failure-injection review, including
authorization-consumption races, journal-write failure, modeled executor
disconnects, duplicate/reordered evidence, postcondition mismatch, and recovery
authorization boundaries.
