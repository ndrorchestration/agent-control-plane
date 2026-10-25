# ACP Differentiation Note — Against Stonebranch's Hybrid Orchestration Control Plane (UAC 8.1)

**Status: DRAFT for Ender's review, 2026-10-25. Not published anywhere.**
**Grounding:** ACP claims below are grounded in a live read of the
`ndrorchestration/agent-control-plane` README (2026-10-25). Stonebranch claims
are from its October 8, 2026 BusinessWire press release ONLY — vendor claims,
not verified against the product or its documentation. Do not cite the release's
Gartner statistic (95% of I&O workflows with an agentic step by 2030) as fact;
it carries the standard no-endorsement disclaimer.

## The thesis in one line

Stonebranch governs workflows. ACP separates the question of **what happened**
from the question of **what is authorized next** — and refuses to let the first
answer the second.

## Where they converge (say so plainly — convergence validates the thesis)

| Shared move | Stonebranch (release claim) | ACP (implemented / designed) |
|---|---|---|
| Deciding vs. doing split | "Agents reason and request, while governed workflows control execution." Agents call approved workflows via tool calls, never enterprise systems directly. | Deterministic dispatch gated by explicit policy allow/deny decisions; fail-closed rejection of unknown capabilities. |
| Credential broker | "Credentials stay in UAC and are not exposed to the agent by default." | Credential broker separated from execution in the architecture (Provider → Capability → Transport/Adapter → Effect/Risk → Policy); credentials are not ambient to the agent. |
| Human approvals first-class | Approvals run as a step type inside the end-to-end workflow. | Human decisions are a distinct step in the control-plane layer, not a bolt-on. |
| Auditability named | "Traceable record from request to outcome," plus monitoring, retries, exception handling. | Run-scoped provenance manifests recording task identity, lifecycle, capability invoked, and policy decision. |

## Where Stonebranch is ahead (no defensiveness — state it)

- **Shipping product, enterprise scope.** UAC 8.1 is available now with an
  installed base, covering deterministic jobs, events, applications, and
  infrastructure alongside agent actions. ACP is experimental engineering, not a
  production orchestrator, security boundary, or distributed control plane.
- **Operational breadth.** Retries, exception handling, dependency management,
  recovery controls, and service levels across every execution type. ACP does
  not center this machinery.
- **Authoring path.** The AI Workflow Builder turns a natural-language
  description into a workflow, refined visually, run under the same governance.
  ACP has no equivalent authoring story.

## Where ACP goes further (the differentiation — this is the edge)

### 1. Receipt is evidence, never authority

Stonebranch's "traceable record" proves something happened. ACP splits that
record into two separate objects that must never be merged:

- **Provenance manifest** — what ran, which capability was invoked, what the
  policy decision was. This is evidence of execution.
- **Authority envelope** — what may run next, as a bounded, revocable,
  observable envelope (candidates implemented for envelope, revocation,
  authority-state, sync, and watermark under bounded test conditions).

A manifest never authorizes the next action. Follow-on authorization is a
**fresh decision**, not a continuation of the previous run. Stonebranch's
release describes no equivalent separation and no follow-on authorization
object — once a governed workflow runs, nothing in the release gates what
comes next.

### 2. Fail-closed at dispatch, not retries after the fact

ACP rejects unknown capabilities outright and enforces cooperative execution
budgets (reported steps, tool calls, tokens, cost) at dispatch time.
Stonebranch's failure story is retries and recovery — availability-oriented.
Fail-closed denial and availability-oriented recovery are different postures,
and ACP's is the stricter one.

### 3. Capability discipline as a primitive

Capability registration with duplicate-registration rejection, deterministic
dispatch and cancellation semantics, and authority as a bounded envelope rather
than an ambient grant. Stonebranch attributes enforcement generically to
"governed workflows" — no policy language, no least-privilege scoping, and no
stated violation behavior (deny, block, escalate, rollback) appear in the
release.

### 4. Ceilings stated as a feature, not an apology

ACP's README states what is NOT established, and this note preserves that
list verbatim in spirit: no production reliability, no security certification,
no independent validation, no distributed-system reliability, no model/provider
integration, no automatic metering, no durable external audit logging, no
tamper-evident provenance, no autonomous background operation, no cross-runtime
portability evidence, no governance efficacy. A design that names its
non-claims is more trustworthy than a release that implies them.

## What ACP will NOT chase (scope discipline)

- Enterprise job-scheduling breadth (deterministic jobs, events, infra).
- SLA / recovery / retries ops machinery as a core feature.
- Natural-language workflow authoring.

Chasing any of these dilutes the edge. They are Stonebranch's moat
(installed base + ops machinery), not ACP's argument.

## The line to use

> Stonebranch ships governed workflows. ACP answers the question their
> release leaves open: a record of what happened is not permission for what
> happens next. Provenance and authority are separate objects, and the second
> one requires a fresh decision every time.

## Sources

- Stonebranch press release, BusinessWire, October 8, 2026:
  https://www.businesswire.com/news/home/20261008712204/en/Stonebranch-Launches-Hybrid-Orchestration-Control-Plane-to-Provide-Governed-Reliability-in-the-Agentic-Era
- `ndrorchestration/agent-control-plane` README (live read 2026-10-25):
  experimental Python control-plane kernel; implemented surface and
  not-established list as summarized above.
- ACP architecture as recorded in Ender's notes: Provider → Capability →
  Transport/Adapter → Effect/Risk → Policy; PDP/PEP/credential broker/
  execution/receipt/follow-on authorization separation. ACP PR #173 was ready
  per the 2026-10-14 record; its current state was not re-verified for this note.

## Placement (Ender's word required — nothing placed yet)

- [ ] Keep as a working draft only.
- [ ] Add as a related-work section in the ACP repo (README or docs/).
- [ ] Adapt for the portfolio (ai-prompt-systems-portfolio) as a positioning page.
- [ ] Use as interview talking points only (no publication).
