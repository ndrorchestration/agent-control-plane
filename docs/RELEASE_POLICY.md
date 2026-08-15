# Release and Evidence Policy

## Versioning

ACP uses semantic software versioning for implemented interfaces. Version numbers describe artifact/API evolution; they do not represent scientific validation, autonomy, governance effectiveness, or production readiness.

Current development line: `0.1.x`.

## Evidence states

Implementation maturity is tracked independently from version:

`DEFINED → IMPLEMENTED → TESTED → CI-VERIFIED → EMPIRICALLY EVALUATED → PRODUCTION-READY`

A later state must not be inferred from an earlier one.

## Release gates

### 0.1.x
Local deterministic kernel, tests, provenance, policy boundary, and evaluation harness may evolve within the development line.

### 0.2.x candidate
Requires a documented integration contract and broader regression/evaluation coverage. This is a planning threshold, not a promise.

### 1.0.0 candidate
Requires stable public interfaces plus evidence appropriate to every capability claimed as stable. Production readiness requires separate operational, security, reliability, and deployment evidence.

## Epistemic rule

A release tag is never evidence that a scientific, mathematical, governance, or safety claim has been validated. Such claims require their own reproducible artifacts and evidence records.
