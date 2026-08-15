# Release and Evidence Policy

## Current posture

ACP is an experimental deterministic local control-plane kernel. It has routing, lifecycle, policy, provenance, invariants, an evaluation harness, and CI-tested behavior. It is not yet a production, distributed, or autonomous control plane.

## Versioning

The package currently uses `0.1.0`. Continue within `0.1.x` while the kernel contract and evaluation surface are evolving. Promote to `1.0.0` only when a stable API, compatibility policy, security model, integration contract, and broader reliability evidence exist.

## Evidence rule

Passing unit/integration tests establishes only the tested local behavior. It does not establish distributed correctness, security effectiveness, model quality, autonomous behavior, or production reliability.

Release notes should state both implementation changes and evidence changes separately.
