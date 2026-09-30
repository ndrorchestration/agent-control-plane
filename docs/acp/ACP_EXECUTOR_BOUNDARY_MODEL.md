# ACP Executor Boundary Model

## Purpose

This document defines the minimum boundary model required before ACP executor or rollback executor work can advance beyond draft/HOLD.

ACP currently distinguishes between:

1. Read-only observation
2. Non-executing journal or result binding
3. Mutation intent
4. Live mutation execution
5. Rollback execution

Only the first two categories may advance before this boundary model is complete.

## 1. Filesystem object identity / TOCTOU

Tracked by issue #117.

### Problem

An executor must not rely only on a path string when deciding what object it is about to mutate. A path may refer to a different object between inspection and execution.

### Required model

Before mutation, ACP must define how it identifies the target object.

Candidate identity evidence may include:

- Canonical path
- File ID / inode or platform-equivalent object identifier
- Content hash
- Size
- Last modified timestamp
- Open handle identity where applicable
- Repository state / commit identity where applicable

### Required fail-closed behavior

ACP must refuse mutation when:

- The object inspected is not the object about to be mutated.
- The object changed after inspection.
- Identity evidence is missing.
- Identity evidence conflicts.
- The executor cannot prove that the mutation target matches the authorized target.

## 2. Trusted process boundary / identity / isolation

Tracked by issue #118.

### Problem

A live executor must prove that the process performing mutation is authorized, isolated, and operating within its declared capability boundary.

### Required model

ACP must define:

- What process is trusted.
- How the process identity is established.
- What credentials or capabilities it holds.
- What repository or filesystem scope it may mutate.
- What environment it runs in.
- What isolation boundary prevents unintended mutation.
- How pre-mutation and post-mutation evidence is emitted.

### Required fail-closed behavior

ACP must refuse mutation when:

- The process identity is unknown.
- The process is outside the trusted execution boundary.
- The process has broader authority than declared.
- The execution environment cannot be bound to the evidence record.
- The mutation cannot be attributed to the authorized executor.

## 3. Mutation evidence contract

Before live mutation, ACP must emit evidence for:

- Requested action
- Authorized target
- Pre-mutation object identity
- Executor identity
- Execution boundary
- Capability scope
- Mutation result
- Post-mutation object identity
- Error or refusal state
- Rollback availability, if applicable

## 4. Rollback evidence contract

Rollback is also mutation.

Rollback ACP work must not be treated as lower risk than forward mutation.

Rollback evidence must include:

- Original mutation reference
- Rollback target
- Pre-rollback object identity
- Rollback executor identity
- Rollback action
- Post-rollback object identity
- Residual risk or irreversibility notes

## 5. Current authorization state

As of 2026-09-30:

- Non-executing rollback-recovery journal semantics: may be rebuilt for review.
- Non-executing result binding: may be rebuilt for review.
- Live repository mutation executor: HOLD.
- Rollback executor: HOLD.
- Consolidated executor hardening: HOLD / review surface only.

## 6. Promotion rule

Executor promotion requires explicit resolution, scoping, or accepted residual-risk treatment for #117 and #118. Passing synthetic repository tests is not sufficient to establish production executor authority, real-project repository authorization, or High-Assurance status.
