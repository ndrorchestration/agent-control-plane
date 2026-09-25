# GSAE-E0 Stage-A Conformance Harness

**Status:** `RESEARCH APPARATUS / EXECUTION NOT AUTHORIZED / NOT RUN / N=0`

**Source under test:** `07a09698ca66e8837d04e6ec05b4de3448eced04`  
**Schema:** `agent-control-plane.execution.v1`  
**Frozen fixture candidate:** `fixtures/stage_a_v1.json`

This package measures a bounded contract-feasibility question. Passing apparatus tests establish only that the measurement apparatus behaves as tested. They do **not** establish GSAE-E0 feasibility, cross-runtime portability, governance efficacy, safety, security, production readiness, or execution authorization.

## Purpose

Stage A asks whether the bound ACP execution contract can represent the frozen ordinary and consequential governance states with stable structured semantics, without semantic overload, runtime-specific reinterpretation, or a core-schema fork.

The harness deliberately measures the existing contract before any schema repair. Missing or ambiguous governance meanings remain evidence. Values hidden only in free-form `detail`, opaque artifact payloads, overloaded status strings, or runtime-specific identifier conventions do not count as structured authority coverage.

## Apparatus verification

Install the repository and test dependency:

```bash
python -m pip install -e . pytest
```

Verify the research apparatus:

```bash
python -m pytest experiments/gsae_e0/tests -v
```

Verify the full repository:

```bash
python -m pytest
```

The repository CI runs the full suite on Python 3.10, 3.11, 3.12, 3.13, and 3.14.

These commands test the apparatus and already-established ACP behavior. They do not execute the frozen canonical Stage-A experiment.

## Source binding

Before an evidence-producing Stage-A run can proceed, the runner requires the exact source-under-test commit to exist in repository history and requires the **frozen Stage-A source surfaces** to be content-equivalent to that source commit.

The frozen path set is: `core.py`, `budget.py`, `policy.py`, `provenance.py`, and the `contract/` package. Those paths cover the kernel, budget, policy, provenance, mapping, and execution-contract behaviors exercised by the frozen Stage-A fixtures.

This deliberately binds the experiment to measured source content rather than branch topology or the entire package directory. Squash/rebase operations may change ancestry while preserving the exact measured source; unrelated future modules may be added without invalidating the frozen target. Any change to the frozen path set still fails closed and requires explicit rebind/retest.

The CI workflow fetches full repository history so this binding can be proven rather than assumed.

Changing the source-under-test SHA, schema version, or ACP source package invalidates the previous source binding for current-state claims and requires an explicit rebind/retest. Historical evidence remains provenance.

## Fixture identity

The frozen candidate manifest contains:

- 10 native ACP conformance fixtures (`NATIVE-01` through `NATIVE-10`);
- 8 negative controls (`NEG-01` through `NEG-08`);
- 10 governance-authority semantic probes (`AUTH-01` through `AUTH-10`).

Its canonical SHA-256 is computed from validated, canonical JSON. The content identity is an apparatus/protocol input identity, not an experiment result.

## Execution authorization boundary

`run_stage_a(...)` requires explicit protocol, authorization-record, run, harness-commit, source, schema, and fixture identities. It fails closed when required identities or bindings are absent.

The function records an authorization-record identifier; it does **not** decide whether that external governance record is valid. The owning GSAE control record remains the authority for whether execution is authorized.

Canonical Stage-A execution must not occur until:

1. the owning GSAE record accepts the protocol freeze;
2. a separate execution-authorization record is issued;
3. the exact apparatus/source/fixture identities are bound to that authorization.

No canonical execution command is documented here while the study remains unauthorized.

## Result dispositions

Stage A can produce only one aggregate contract-feasibility disposition:

- `FEASIBLE_FOR_FROZEN_SCOPE`;
- `CONDITIONALLY_FEASIBLE_NARROW`;
- `NOT_FEASIBLE_FOR_FROZEN_SCOPE`;
- `NOT_ESTABLISHED`.

A high numerical coverage rate cannot override a critical missing or ambiguous semantic. Missing required evidence produces `NOT_ESTABLISHED`; it is never imputed.

These dispositions are not authorization, safety, efficacy, portability, or production-readiness conclusions.

## Evidence bundle

The in-memory evidence bundle binds, at minimum:

- experiment and protocol identities;
- explicit authorization-record identity;
- source-under-test and harness commit identities;
- schema and fixture-set identities;
- fixture-manifest SHA-256;
- deterministic per-fixture result identities and retry lineage;
- aggregate disposition;
- test command and test summary;
- explicit evidence ceiling.

The semantic bundle hash excludes wall-clock timestamps. Retries receive distinct deterministic result identities and must preserve the immediately prior result identity.

The runner returns the bundle in memory; the apparatus does not silently write or publish canonical result artifacts.

## Known boundary of the current contract candidate

The Stage-A fixture set intentionally probes governance meanings that may be narrower than the current framework-neutral execution contract, including principal identity, resource scope, distinct operation semantics, policy identity/version, explicit decision outcome/reason codes, authority expiry, delegation, and authority conditions.

Their absence from the current typed surface is not pre-declared as an experiment result. The canonical disposition remains unestablished until a separately authorized run evaluates the frozen fixture set.

If an authorized Stage-A run later finds a missing or ambiguous critical semantic, freeze and retain that evidence before proposing a schema extension. Do not repair the contract first and erase the failure that motivated the change.

## Stage B

Cross-runtime portability is a separate Stage-B question. It remains `NOT ESTABLISHED` until a materially different runtime/adapter is selected, bound, and tested under a separate admitted protocol slice. A Stage-A result alone cannot establish portability.
