# ACP Public Surface Review

Date: 2026-09-30

## Purpose

This review keeps the public repository understandable without erasing technical evidence. ACP may remain public, but the public surface should clearly separate front-door explanation, deep design notes, experiments, and unestablished claims.

## Public-facing posture

ACP should be described as:

> Experimental control-plane kernel for bounded agent execution, policy checks, provenance, authority envelopes, and fail-closed workflow supervision.

Avoid describing ACP as a production orchestrator, security boundary, autonomous runtime, distributed control plane, or independently validated governance system unless those claims are separately established.

## Recommended GitHub About description

```text
Experimental control-plane kernel for bounded agent execution, policy checks, provenance, authority envelopes, and fail-closed workflow supervision.
```

## Recommended topics

```text
agent-control-plane
ai-governance
agentic-ai
workflow-governance
provenance
authority-model
fail-closed
python
multi-agent-systems
experimental
```

## Public-surface categories

| Category | Examples | Public handling |
|---|---|---|
| Front door | `README.md` | Short, clear, bounded, non-claim-inflating. |
| Core technical spec | `docs/CONTROL_PLANE_KERNEL_SPEC.md` | Public as design/implementation evidence. |
| Evidence/release policy | `docs/RELEASE_AND_EVIDENCE_POLICY.md` | Public; useful for claim discipline. |
| Development frontier | `docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md` | Public only as provisional development evidence. |
| Ecosystem handoff | `docs/ECOSYSTEM_HANDOFF.md` | Review for internal routing details before promotion. |
| Remote adapter/mutation docs | `docs/REMOTE_*`, `docs/REMOTE_DESKTOP_COMMANDER_ADAPTER.md` | Public only with careful authority and safety framing. |
| Experiments/integration | `experiments/`, `integration/` | Public if no secrets/private endpoints and clearly experimental. |

## Review checklist before public promotion

Check public files for:

- secrets, tokens, API keys, signing keys, private endpoint URLs, or tunnel URLs;
- local usernames, personal machine paths, private directory structures, or private hostnames;
- operational instructions that imply live remote mutation authority;
- language that implies production readiness, security certification, independent validation, or governance efficacy;
- unqualified words such as `secure`, `trusted`, `production`, `autonomous`, `guaranteed`, `validated`, or `certified` when the evidence is only local/bounded;
- stale dates or source-state references that could be mistaken for current assurance;
- instructions that depend on non-public infrastructure.

## Boundary language to preserve

Use this style of language when writing public docs:

- `experimental engineering`
- `bounded candidate`
- `local invariant under tested conditions`
- `not a production security boundary`
- `not independently validated`
- `does not establish governance efficacy`
- `does not imply autonomous background execution`

## Boundary language to avoid unless separately evidenced

Avoid unsupported claims such as:

- `production-ready`
- `secure by design`
- `independently validated`
- `autonomous control plane`
- `distributed reliability guaranteed`
- `governance efficacy established`
- `cross-runtime portability proven`

## Current cleanup result

The README has been converted into a concise public front door. The dense candidate inventory has been moved into `docs/CURRENT_IMPLEMENTATION_INVENTORY.md` as a deeper engineering ledger. This preserves transparency while reducing public-facing cognitive load.
