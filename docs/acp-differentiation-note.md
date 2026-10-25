# ACP Differentiation Note — Against Stonebranch's Hybrid Orchestration Control Plane (UAC 8.1)

**Status: DRAFT for Ender's review, 2026-10-25; amended 2026-10-25 per external
critique and live verification. PR #174 open, unmerged. Not published anywhere else.**
**Grounding:** ACP claims below are grounded in live reads of the
`ndrorchestration/agent-control-plane` README and executor source (2026-10-25).
Stonebranch claims are from its October 8, 2026 BusinessWire press release
ONLY, except where platform documentation is noted — vendor claims, not
verified against the product itself. Do not cite the release's Gartner
statistic (95% of I&O workflows with an agentic step by 2030) as fact; it
carries the standard no-endorsement disclaimer.

## The thesis in one line

Stonebranch governs workflows. ACP separates the question of **what happened**
from the question of **what is authorized next** — and refuses to let the first
answer the second.

## Three questions, answered separately (correction, 2026-10-25)

An earlier draft of this note framed the comparison as ACP "going further"
than Stonebranch. That overreads the evidence. The defensible framing is three
separate questions:

- **Is ACP specialized? Yes.** Its explicit focus on post-execution authority,
  provenance, and fail-closed admission is demonstrably specialized — see the
  typed contract in §"Where ACP specializes" below.
- **Is ACP specialized in ways Stonebranch does not emphasize? Yes, based on
  the documentation reviewed** — particularly how execution receipts relate to
  subsequent authorization. Stonebranch's release does not specify
  follow-on authorization semantics.
- **Has ACP demonstrated capabilities Stonebranch cannot match? Not yet.**
  That requires comparative testing or evidence of architectural limitations
  in Stonebranch's implementation. Technical novelty, exclusivity, and
  comparative security superiority are **NOT ESTABLISHED** and are not claimed
  here.

## Where they converge (say so plainly — convergence validates the thesis)

| Shared move | Stonebranch (release claim) | ACP (implemented / designed) |
|---|---|---|
| Deciding vs. doing split | "Agents reason and request, while governed workflows control execution." Agents call approved workflows via tool calls, never enterprise systems directly. | Deterministic dispatch gated by explicit policy allow/deny decisions; fail-closed rejection of unknown capabilities. |
| Credential broker | "Credentials stay in UAC and are not exposed to the agent by default." | Credential broker separated from execution in the architecture (Provider → Capability → Transport/Adapter → Effect/Risk → Policy); credentials are not ambient to the agent. |
| Human approvals first-class | Approvals run as a step type inside the end-to-end workflow. | Human decisions are a distinct step in the control-plane layer, not a bolt-on. |
| Auditability named | "Traceable record from request to outcome," plus monitoring, retries, exception handling. | Run-scoped provenance manifests recording task identity, lifecycle, capability invoked, and policy decision. |

Correction to the earlier draft: it would be incorrect to characterize
Stonebranch as merely recording execution without enforcing authorization.
Their platform documentation confirms roles/permissions and audit records
generally (older Controller documentation; the 8.1 agentic surface was not
independently verified for this note). What remains unestablished from public
material is whether Stonebranch enforces equivalent receipt→authority
separation internally — not whether it enforces authorization at all.

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

## Where ACP specializes (not a superiority claim)

### 1. Receipt is evidence, never authority

Stonebranch's "traceable record" proves something happened. ACP splits that
record into two separate objects that must never be merged:

- **Provenance manifest** — what ran, which capability was invoked, what the
  policy decision was. This is evidence of execution.
- **Authority envelope** — what may run next, as a bounded, revocable,
  observable envelope (candidates implemented for envelope, revocation,
  authority-state, sync, and watermark under bounded test conditions).

A manifest never authorizes the next action. Follow-on authorization is a
**fresh decision**, not a continuation of the previous run. This is not a
philosophical position only — it is a typed contract in the implementation,
verified live 2026-10-25 in `src/agent_control_plane/remote_mutation_executor.py`:

- execution results carry `authority_effect=NONE`;
- `follow_on_authority=FRESH_ADJUDICATION_REQUIRED`;
- the executor raises on "execution result cannot carry authority" and on
  "follow-on effects require fresh adjudication";
- the executor is flagged `bounded_local_test_only=True`.

Bounded scope, stated honestly: the durable local mutation lineage behind
this was established under bounded disposable-repository conditions (bounded
executor posture PR #156, durable lineage PR #159, implementation baseline
through merged PR #170 per `docs/CURRENT_FRONTIER.md`, 2026-10-04). The
specific chained-mutation test coverage was not re-verified for this note.

What Stonebranch's public material does NOT establish is an equivalent
separation: the press release specifies no follow-on authorization semantics,
and whether their implementation enforces them internally is unknown from
public sources. That is a gap in public evidence, not a demonstrated ACP win.

### 2. Fail-closed at dispatch, not retries after the fact

ACP rejects unknown capabilities outright and enforces cooperative execution
budgets (reported steps, tool calls, tokens, cost) at dispatch time.
Stonebranch's failure story is retries and recovery — availability-oriented.
These are different postures for different layers, not a ranking: fail-closed
at the authorization boundary, retries at execution after authorization is
granted. ACP's specialization is the first layer.

### 3. Capability discipline as a primitive

Capability registration with duplicate-registration rejection, deterministic
dispatch and cancellation semantics, and authority as a bounded envelope rather
than an ambient grant. Stonebranch's release attributes enforcement generically
to "governed workflows" — no policy language, no least-privilege scoping, and
no stated violation behavior (deny, block, escalate, rollback) appear in the
release. Their platform documentation separately confirms roles/permissions
and audit records; the gap is specifically about receipt→authority semantics,
not about authorization in general.

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

Chasing any of these dilutes the specialization. They are Stonebranch's moat
(installed base + ops machinery), not ACP's argument.

## Next experiment (highest-value follow-up, not another description)

Demonstrate, reproducibly and in public, that a valid historical receipt,
presented without fresh authorization, cannot authorize a second consequential
action. ACP already has much of the necessary test machinery in the bounded
executor. Turning that into a clean public demonstration would strengthen the
portfolio without pretending to prove that Stonebranch fails the same test.
That demonstration — not another architectural description — is what would
move the third question above from "not established" toward "demonstrated."

## The line to use

> Stonebranch ships governed workflows. ACP's specialization is the boundary
> they leave unspecified: a record of what happened is not permission for
> what happens next. Provenance and authority are separate objects, and the
> second one requires a fresh decision every time. Whether that separation
> outperforms or is unique against Stonebranch's implementation is not
> established — and this note does not claim otherwise.

## Sources

- Stonebranch press release, BusinessWire, October 8, 2026:
  https://www.businesswire.com/news/home/20261008712204/en/Stonebranch-Launches-Hybrid-Orchestration-Control-Plane-to-Provide-Governed-Reliability-in-the-Agentic-Era
- `ndrorchestration/agent-control-plane` README (live read 2026-10-25):
  experimental Python control-plane kernel; implemented surface and
  not-established list as summarized above.
- `src/agent_control_plane/remote_mutation_executor.py` (live code read
  2026-10-25): `authority_effect=NONE`,
  `follow_on_authority=FRESH_ADJUDICATION_REQUIRED`, `bounded_local_test_only`.
- `docs/CURRENT_FRONTIER.md` (2026-10-04): implementation baseline through
  merged PR #170; bounded executor posture PR #156; durable local mutation
  lineage PR #159.
- ACP architecture as recorded in Ender's notes: Provider → Capability →
  Transport/Adapter → Effect/Risk → Policy; PDP/PEP/credential broker/
  execution/receipt/follow-on authorization separation. ACP PR #173 was ready
  per the 2026-10-14 record; its current state was not re-verified for this note.
- Stonebranch platform documentation (general, older Controller docs):
  roles/permissions and audit records confirmed; 8.1 agentic-surface
  enforcement specifics not independently verified for this note.

## Placement (Ender's word required for merge — PR open, unmerged)

- PR #174 opened 2026-10-25 (branch `docs/acp-differentiation-note` → main);
  this amendment applies to that branch. Merge requires Ender's explicit word.
- [ ] Adapt for the portfolio (ai-prompt-systems-portfolio) as a positioning page.
- [ ] Use as interview talking points only (no further publication).
