# Release and Evidence Policy

## Current posture

ACP is an experimental deterministic local control-plane kernel. It has routing, lifecycle, policy, provenance, invariants, an evaluation harness, and CI-tested behavior. It is not yet a production, distributed, or autonomous control plane.

## Evidence progression

`DEFINED → IMPLEMENTED → TESTED → INTEGRATION-VERIFIED → BENCHMARKED → OPERATIONALLY VALIDATED`

These states apply to individual capabilities, not the repository as a whole.

## Versioning

The package currently uses `0.1.0`. Continue within `0.1.x` while the kernel contract and evaluation surface are evolving. Promote to `1.0.0` only when a stable API, compatibility policy, security model, integration contract, and broader reliability evidence exist.

## Evidence rule

Passing unit/integration tests establishes only the tested local behavior. It does not establish distributed correctness, security effectiveness, model quality, autonomous behavior, or production reliability.

Benchmarks establish measured behavior under documented conditions. Operational validation requires representative deployment conditions, failure modes, security controls, and reproducible evidence.

Release notes should state both implementation changes and evidence changes separately.

## Ecosystem boundary

ACP can provide infrastructure to DGAF, Amethyst, Driftwatch, PDMAL, Acoustic-Mesh, or other projects. An integration must be tested before the receiving project is described as ACP-validated. Shared terminology does not establish implementation equivalence.

## Historical evidence

Historical test or benchmark results remain provenance unless reproduced against the current implementation and environment.
