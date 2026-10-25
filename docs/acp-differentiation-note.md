# Related Work: Stonebranch UAC 8.1 and ACP's Post-Execution Authority Boundary

**Status:** DRAFT — comparative engineering note, 2026-10-25. Proposed in
[PR #174](https://github.com/ndrorchestration/agent-control-plane/pull/174);
not merged or independently validated. Stonebranch descriptions below are
vendor documentation and release claims, not hands-on product verification.
ACP descriptions are derived from the current repository README, implementation
inventory, and frontier record; source inspection is not an independent audit.

## Summary

Stonebranch's Hybrid Orchestration Control Plane, announced with Universal
Automation Center (UAC) 8.1 on 2026-10-08, combines workflows, agent requests,
approvals, automation and operational controls. This is evidence of **industry
interest in separating agent reasoning from governed execution**, not evidence
that any particular ACP security claim has been externally validated.

**ACP's narrower research focus:** an execution result or provenance receipt is
evidence about a past action, *not authority* to perform the next consequential
action. Its documented post-execution invariant is:

```text
ACTION -> AUTHORIZATION -> EXECUTION -> RESULT/EVIDENCE
       -> FRESH ADJUDICATION REQUIRED -> NEW AUTHORIZATION -> FOLLOW-ON ACTION
```

ACP records tested local primitives and bounded disposable-repository executor
lineage/fresh-adjudication behavior. Its authority envelope, revocation,
authority-state, sync and watermark surfaces include **candidate** implementations.
This is not a production authorization system.

## Convergence and differences in emphasis

| Question | Stonebranch UAC 8.1 (vendor-reported) | ACP (repository-documented) |
|---|---|---|
| Who may execute? | Agents request governed workflows; UAC applies permissions, business rules and RBAC. | Local deterministic dispatch with explicit policy decisions and rejection of unknown capabilities. |
| How are secrets handled? | Credentials retained within UAC rather than exposed to agents by default. | Credential-broker separation is an **architectural proposal**; not an established production secret-isolation guarantee. |
| Where does human approval sit? | Approval Tasks can pause workflow progression until configured approvers act. | Human decision and fresh-adjudication semantics are modeled in proposed architecture and bounded action contracts. No equivalent operational workflow product is claimed. |
| How is the record kept? | Audits, task histories, AI/service logs and traceability are vendor-documented. | In-memory run-scoped provenance manifest and typed execution/evidence identity primitives; no durable external, tamper-evident audit guarantee. |
| What governs a subsequent effect? | RBAC checks apply to actions; approvals/dependencies may control downstream workflow steps. | Typed fresh-adjudication and distinct authorization for explicitly chained mutations, demonstrated only in bounded disposable-repository scope as documented in CURRENT_FRONTIER. |

### Important limitation on competitive differentiation

Stonebranch's announcement does **not** state a typed, receipt-to-follow-on
authorization non-transfer rule comparable to the ACP invariant above.
However, its 8.1 security and approval documentation **does** describe action
authorization, controller-enforced RBAC, MCP tool whitelisting, approval tasks
and workflow dependency conditions. Absence of a named ACP-style object in the
reviewed public material **does not prove absence of equivalent behavior** in
Stonebranch's product.

The defensible distinction is **specificity of ACP's exposed post-execution
authority contract and falsifiable engineering focus**, not comparative
superiority, first invention, stronger enforcement, or proof of a missing vendor
security boundary.

### Different optimization targets

Stonebranch documents a shipping enterprise orchestration product with retries,
recovery controls, scheduling/dependencies, SLAs and natural-language workflow
authoring. ACP is experimental kernel and governance research. ACP's local
fail-closed rejection and cooperative resource budgets are useful engineering
tests, but cooperative accounting **does not** enforce a hostile process or
provider's real resource usage. Availability/recovery and denial are not mutually
exclusive: vendor documentation includes both governance and operational controls.

## Deliberate non-goals

Do not expand ACP to chase parity with Stonebranch's enterprise scheduling,
SLA/retry/recovery product suite or AI Workflow Builder. ACP has bounded
supervisor/retry candidates, but they do not justify enterprise-operational
equivalence. Prefer a small reproducible authorization/receipt test over a broad
feature imitation.

## Candidate falsification / comparison protocol (NOT executed)

1. **Receipt laundering:** provide a valid past execution receipt but no new
   authorization; require denial of a subsequent consequential action.
2. **Stale approval:** revoke, expire or alter the bound scope between first and
   second actions; require fresh decision and denial when authorization is stale.
3. **Changed effect:** keep receipt and identity but vary target, operation or
   argument; require denial unless a current policy explicitly authorizes it.
4. **Omitted lineage:** remove the caller-supplied previous closure; verify
   behavior against ACP's bounded durable local lineage, without inferring
   distributed/global protection.
5. **Controls mapping for UAC:** compare documented RBAC, Approval Tasks,
   workflow dependencies and audit records against these properties without
   claiming an execution experiment on UAC. A true product-to-product benchmark
   would require access, matched fixtures, rule versions and independent review.

Record fixture, policy/identity versions, timestamps, raw decisions,
runtime/environment, source commit and negative outcomes. A local self-test is
not independent validation.

## Career / portfolio-safe translation

**Short interview line:** "Enterprise orchestration vendors increasingly
separate agents requesting actions from governed systems executing them. My ACP
research targets a narrower failure mode: a successful execution receipt must
never silently become permission for the next action."

**Technical follow-up:** "In bounded local tests, ACP implements deterministic
dispatch, explicit policy checks and run-scoped provenance; its disposable-repo
executor contract includes typed fresh adjudication for chained actions.
Production security, distributed lineage and independent validation remain
unestablished."

Do **not** say "ahead of Stonebranch," "more secure than UAC," "Stonebranch lacks
fresh authorization," "production-ready," or "independently validated."

## Claims ceiling

ACP's README explicitly does not establish production reliability, security
certification, independent validation, distributed reliability, general
model/provider integration, automatic metering, durable external audit logging,
tamper-evident provenance, autonomous background operation, cross-runtime
portability or governance efficacy. `docs/CURRENT_FRONTIER.md` additionally
limits mutation execution to `BOUNDED_LOCAL_TEST` disposable-repository scope;
real-project mutation and rollback execution remain unauthorized. Do not
promote DGAF scientific/High-Assurance claims through this related-work note.

## Sources and evidence type

- [Stonebranch announcement, 2026-10-08](https://www.stonebranch.com/news/stonebranch-launches-hybrid-orchestration-control-plane-to-provide-governed-reliability-in-the-agentic-era) — **vendor release** (UAC 8.1 features, positioning, availability).
- [Stonebranch Robi AI Security & Privacy FAQ, UAC 8.1](https://documentation.stonebranch.com/uac/ai/robi-faq) — **vendor product documentation** (RBAC, approvals, MCP tool whitelisting, audit).
- [Stonebranch UAC Approval Task documentation, v8.1](https://documentation.stonebranch.com/uac/uc/approval-task) — **vendor product documentation** (approval conditions and workflow pauses).
- [Stonebranch workflow dependencies](https://documentation.stonebranch.com/uac/8.0/uc/creating-and-maintaining-workflows) — **vendor documentation for v8.0**, not independently verified as exact UAC 8.1 behavior.
- [ACP README](../README.md), [implementation inventory](CURRENT_IMPLEMENTATION_INVENTORY.md), [frontier and scope](CURRENT_FRONTIER.md) — **repository-authored engineering claims and boundaries**.
- [ACP PR #156](https://github.com/ndrorchestration/agent-control-plane/pull/156), [PR #159](https://github.com/ndrorchestration/agent-control-plane/pull/159) — **historical bounded implementation/review provenance**.

**Review gates:** confirm live exact-head implementation/tests, correct vendor
documentation versioning, independent reviewer scrutiny if claiming comparative
performance, and explicit approval before promoting this draft into public
portfolio claims. This proposed PR is public to repository visitors; it is
**not yet part of protected main**.
