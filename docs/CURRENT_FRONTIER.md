# ACP Current Frontier

Date: 2026-09-30

## Purpose

This file is the current public-facing frontier pointer for Agent Control Plane (ACP). It exists so older dated frontier notes can remain as historical evidence without being mistaken for the current repository status.

## Current public surface

Merged PR #141 clarified the public repository surface by:

- converting `README.md` into a concise front door;
- adding `docs/CURRENT_IMPLEMENTATION_INVENTORY.md` as the deeper engineering inventory surface;
- adding `docs/PUBLIC_SURFACE_REVIEW.md` as the public-surface framing checklist;
- aligning `pyproject.toml` package metadata with bounded experimental language.

The repository About/topics metadata update remains tracked in issue #142 because it requires a repository settings change outside the code/docs surface.

## Current boundary

ACP remains experimental engineering infrastructure. It is not a production orchestrator, security boundary, autonomous agent runtime, distributed control plane, or independently validated governance system.

Remote mutation remains non-executing unless and until a separate reviewed executor composition is accepted. Existing remote mutation documents describe authorization/evidence contracts, not a live ACP mutation executor.

## Historical frontier notes

`docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md` is retained as historical development evidence. It should not be treated as the current complete repository state after #141 and any later public-surface work.

When updating public-facing docs, link to this file for the current frontier and retain dated files only as historical snapshots.