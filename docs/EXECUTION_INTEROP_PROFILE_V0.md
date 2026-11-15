# ACP execution-v1 interoperability profile (bounded candidate)

Status: **draft / non-authorizing / engineering evaluation only**.
Owner: Agent Control Plane (ACP) execution-contract adapter boundary.
DGAF retains its separate governance, admission, evidence-sufficiency, and
scientific-state authorities. This profile does not update those states.

## Existing source of truth

The ACP `agent-control-plane.execution.v1` immutable Python records remain
the owning execution/event contract in
`src/agent_control_plane/contract/model.py`.
The adapter is deliberately outside the frozen ACP package at
`integration/execution_v1_interop.py` to preserve source-bound Stage-A
experimental invariants. The additive JSON Schema (`contracts/execution.v1.schema.json`) describes
their current `ExecutionEvent.to_dict()` representation. It is not a new
state engine, policy decision point, or independently authoritative claim.

No existing ACP event IDs, execution IDs, trace IDs, provenance records,
legacy mapping semantics, budgets, authorizations, or kernel behavior change.

## Narrow mappings in this candidate

- **JSON Schema Draft 2020-12**: strict closed-object contract for serialized
  native execution-v1 events. `null` is retained for serialized optional
  fields. A separate JSON Schema validator is used for conformance tests;
  Python runtime imports remain dependency-free.
- **CloudEvents 1.0 JSON**: `to_cloudevent` wraps the *complete* native
  execution record as JSON `data`; `from_cloudevent` reconstructs through
  ACP's existing validation and rejects missing, extra, or inconsistent
  envelope fields in this intentionally strict ACP profile. The event type
  is a fixed ACP profile identifier; original lifecycle event type remains
  within `data.event_type`.
- **Event ID**: deterministic SHA-256 of canonical JSON bytes with
  sorted keys, compact separators, UTF-8, and no NaN. Together with the
  source, the digest is a de-duplication/content identity; it is **not**
  a signature, authentic custody, replay protection, or proof the event
  actually occurred. Repeated equivalent event contents deduplicate.
- **OpenTelemetry context only**: `to_otel_trace_context` exposes existing
  32-lowercase-hex trace IDs and 16-lowercase-hex span IDs when nonzero,
  including optional valid parent span. Current ACP legacy IDs such as
  `trace-1` are **rejected**, never rewritten or fabricated. This is not
  an OpenTelemetry SDK integration, export, reconstruction test, or OTLP span.

The `source` attribute is a URI-reference derived from URI-escaped ACP
runtime and component identities. This identifies an ACP producer context,
not an authenticated external principal.

## Claims this slice does not establish

No MCP/A2A implementation, provider adapter, authenticated signatures,
durable custody, tamper-evident provenance, telemetry completeness,
distributed replay guarantees, OTel collector/exporter, independent runtime,
cross-runtime interoperability, production readiness, external validation,
or scientific-N change is established here.

In particular:

`execution happened != execution correct != evidence sufficient != claim authorized != further action permitted`

Neither `from_cloudevent` nor `to_otel_trace_context` consults a
policy engine or grants authority. A successful export is observation
compatibility at most. For consequential follow-on actions, require separate
fresh DGAF adjudication and new authorization.

## Local and hosted validation

```bash
python -m pip install -e . pytest "jsonschema>=4.23,<5"
python -m pytest tests/test_contract.py tests/test_contract_roundtrip.py tests/test_contract_interop.py
```

Hosted `.github/workflows/test.yml` continues to run the full suite on
Python 3.10–3.14 with JSON Schema test support. Record the **exact head SHA**
and CI run evidence when available. A CI PASS is same-system engineering
verification and cannot by itself establish an independent conformance gate.

## Future gates (not implemented)

1. Fixture parity across **two materially different runtimes** using the
   exact same event schema; include version drift and malformed payloads.
2. OTel real SDK/export/collector reconstruction with missing or sampled
   span tests and confidentiality classification.
3. Signed in-toto attestation and independent custody verification,
   separated from mere hashes.
4. MCP/A2A adapter admission and fail-closed deny/revocation tests.
5. Independent operator review before any broader assurance claims.

References: CloudEvents 1.0 specification; OpenTelemetry SpanContext API;
JSON Schema Draft 2020-12. Versions and external support should be pinned
in a later adapter-specific ADR, not inferred from a general roadmap.
