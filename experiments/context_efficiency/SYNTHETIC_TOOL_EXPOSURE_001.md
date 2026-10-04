# CEP Synthetic Tool-Exposure Harness 001

Purpose: test the **measurement and selection mechanism** for capability-driven
tool gating before applying it to a live connector catalog.

This is synthetic engineering characterization, not evidence of ecosystem-wide
token savings.

## Catalog

The fixture contains 8 explicit tool descriptors spanning GitHub, Notion, RDC,
and web capabilities.

Task class: exact-head GitHub workflow-status lookup.

Declared required capability:

`github.status`

## Control

Baseline policy: expose the full explicit catalog.

Expected descriptor exposure: **8**.

## Candidate treatment

Policy: expose descriptors whose declared capability intersects the task's
required capability set.

Expected descriptor exposure: **1**:
`github.workflow_runs`.

## Primary characterization

Descriptor-count reduction in this fixture:

`8 → 1`

This is a **tool-descriptor exposure result**, not a token-reduction result.
No token savings are claimed until schema serialization/tokenization is measured.

## Preservation boundary

The selector:
- returns descriptors only;
- cannot invoke a tool;
- carries no credential;
- carries no authority object;
- cannot mutate ACP policy or task state.

A later live-catalog experiment must additionally preserve task acceptance,
evidence sufficiency, authority boundaries, and exact tool semantics.


## Canonical byte-cost measurement

The harness now also serializes the exposed descriptor set deterministically and
measures exact UTF-8 byte size. This provides a tokenizer-independent context
cost proxy before model-specific tokenization is introduced.

Interpretation boundary:

- descriptor count measures catalog breadth;
- canonical UTF-8 bytes measure serialized exposure size;
- neither is equivalent to model tokens;
- no token-reduction percentage may be claimed until a named tokenizer/version
  is applied reproducibly to the same canonical bytes.

A later tokenizer-specific experiment must record the tokenizer/model family and
version/configuration as part of the measurement identity.
