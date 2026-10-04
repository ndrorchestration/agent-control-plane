# Context Efficiency Plane v0 Candidate

Status: **prototype / characterization only**

This document defines the first bounded implementation tranche for the Context
Efficiency Plane (CEP). It does not establish token savings, correctness
preservation, independent validation, executor authority, or High-Assurance.

## Scope

The initial tranche adds two things only:

1. a strict `ContextState` representation for checkpoint + delta continuation;
2. a baseline measurement contract for observing context/tool exposure.

It does **not** automatically suppress, summarize, retrieve, route, or compact
context.

## Context State Object

The Context State Object separates working state from canonical evidence.

Required fields:

- `task_id`
- `objective`
- `authority_boundaries`
- `evidence` references
- `unresolved`
- `recent_delta`
- `next_action`

Every evidence reference carries:

- source pointer;
- content/source identity;
- optional locator/range;
- `authority_effect`, defaulting to `NONE`.

A compact state object is a projection. It is not evidence authority,
authentication, authorization, or proof of source freshness.

## Preservation rules

1. Canonical evidence remains at its canonical source.
2. Compact state may carry pointers and identities, not substitute summaries as
   authoritative evidence.
3. Authority/claim ceilings must survive checkpointing explicitly.
4. A context checkpoint conveys no follow-on execution authority.
5. Missing critical context must fail closed rather than be silently dropped.
6. SHA-256 produced by this module is content identity only, not authentication.

## Baseline measurement contract

Before changing routing or compaction behavior, record the following per bounded
task:

- total input tokens;
- total output tokens;
- tool-result tokens or equivalent serialized size;
- number of tool schemas/functions exposed;
- number of tools actually invoked;
- retrieval volume;
- number of retrieved items/ranges;
- stable/cacheable prefix size when observable;
- novel prefix size when observable;
- task result / acceptance outcome.

Derived characterization metrics:

`context_efficiency = decision_relevant_input / total_input`

`retrieval_yield = used_or_cited_retrieved_tokens / total_retrieved_tokens`

`tool_utilization = tools_invoked / tool_definitions_exposed`

`context_churn = novel_prefix_tokens / total_prefix_tokens`

If a numerator cannot be observed reliably, record it as unavailable rather than
estimating it as fact.

## First comparison gate

An optimization candidate may advance only if the bounded comparison preserves:

- the same task contract;
- the same or stronger authority-boundary representation;
- canonical evidence references;
- no hidden authority transfer;
- no material correctness regression;

while reducing at least one directly measured context-cost dimension.

## Claim ceiling

`SCIENTIFIC_N_INCREMENT=0`

`INDEPENDENT_VALIDATION=NOT_ESTABLISHED`

`CANONICAL_DGAF_EFFICACY=NOT_ESTABLISHED`

`HIGH_ASSURANCE=NOT_AUTHORIZED`
