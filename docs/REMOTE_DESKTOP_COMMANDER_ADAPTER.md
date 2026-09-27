# Remote Desktop Commander Adapter Candidate

Status: typed read-only remote-execution contract accepted on `main`; mutation-capable execution remains unmerged and not authorized.

## Purpose

Bind ACP's framework-neutral execution contract to evidence returned by an external real-machine executor without making that executor an authority source.

Remote Desktop Commander (RDC) is treated as an execution endpoint. ACP validates request identity and returned evidence. DGAF or another owning governance layer retains authorization and adjudication authority.

## Invariant

Executor != authorizer != evidence adjudicator.

## Current flow

1. Governance admits a bounded read-only action.
2. ACP constructs a device-scoped **typed operation** request.
3. The operation ID and canonical structured parameters are bound by SHA-256 and the signed request envelope.
4. The executor validates device/freshness/replay/root policy and derives fixed argv from ACP's immutable operation registry.
5. Execution uses `shell=False` under bounded runtime/output limits.
6. The executor returns typed result evidence bound to the exact request-envelope SHA-256.
7. ACP validates request/result identity, operation digest, argv, path, completion and side-effect class.
8. Governance decides what claims, if any, the evidence supports.

The historical v1 shell-text path is compatibility-only. New signed execution requests use the typed v2 contract in `docs/TYPED_REMOTE_EXECUTION.md`.

## Implemented candidate checks

- non-empty request, device, profile and working-directory identity;
- exact SHA-256 binding of `command_or_action`;
- request/receipt matching;
- integer exit code;
- artifact SHA-256 syntax validation;
- successful completion requires exit code 0 and `command_completed=true`;
- `READ_ONLY_DISCOVERY` requires no `files_changed`;
- an explicitly false `working_tree_unchanged` fails read-only validation.

## Deliberately not established

The current candidate does establish local HMAC-signed request/receipt integrity, bounded nonce freshness, durable replay rejection, explicit side-effect classes, and receipt-chain linkage. Those controls are local engineering evidence only.

The following remain deliberately **not established**:

- authenticated transport identity between ACP and a remote executor;
- hardware-backed / TPM-rooted device attestation;
- trusted external clock synchronization;
- externally trusted key custody or independent signer identity;
- mutation authorization;
- production security;
- DGAF High-Assurance status;
- scientific independence or scientific-N increment.
## Local evidence — 2026-09-26

Baseline protected-main candidate: `ee8f48faa0af95aeae5336ae34cf4da7ea83723b`.

Baseline full suite before candidate: 556 passed, 4 skipped.

Candidate focused tests: 5 passed, 1 skipped.

Candidate full regression: 561 passed, 5 skipped.

A real local-executor control receipt was then validated using caller-supplied expected request identity, a synthetic/public-safe device identifier, profile `READ_ONLY_DISCOVERY`, working directory, and exact command. Result:

`REMOTE_EXECUTION_RECEIPT=PASS`

The source receipt recorded zero files changed. This establishes local contract composition only; it does not establish trusted remote transport or production authorization.

## Historical next-tranche note — superseded

The earlier next step of adding signed/fresh envelopes, side-effect classes, durable replay handling, and unknown-outcome tests has been implemented and subsequently superseded by the accepted typed v2 read-only execution contract.

The current bounded frontier is documented in `docs/CURRENT_DEVELOPMENT_FRONTIER_2026-09-27.md`: mutation authority admission, transaction planning/rollback identity, and exact plan composition are being reviewed as **non-executing** draft layers before any mutation-capable executor is considered.
## Freshness, replay and unknown-outcome hardening — 2026-09-26

The local candidate now includes a bounded freshness envelope, process-local single-use replay guard, and explicit remote outcome classification.

- freshness requires a non-empty nonce plus integer issue/expiry times;
- requests fail if not-yet-valid or expired;
- the same request-id + nonce pair cannot be consumed twice by the guard;
- receipt outcomes are classified narrowly as `SUCCEEDED`, `FAILED`, or `UNKNOWN`;
- missing/non-true completion evidence is `UNKNOWN`, never inferred success;
- only `SUCCEEDED` can satisfy `assert_known_success`.

Focused adapter tests: 9 passed, 1 skipped. Full ACP regression: 565 passed, 5 skipped.

This remains local candidate evidence. Replay protection is currently process-local rather than durable, and there is still no signed transport envelope or hardware-rooted device identity.

## Durable replay + side-effect-class receipts — 2026-09-26

The candidate now persists consumed request-id + nonce pairs in SQLite so replay rejection survives process restart. The real RDC control runner also emits an explicit `side_effect_class` derived from the bounded execution profile; read-only validation requires both `READ_ONLY_DISCOVERY` and `side_effect_class=READ_ONLY`.

Focused adapter coverage: 11 passed, 1 skipped. Full ACP regression: 567 passed, 5 skipped.

A newly emitted real control receipt containing `side_effect_class=READ_ONLY` was validated end-to-end by ACP: `REMOTE_EXECUTION_RECEIPT=PASS`. This still does not establish signed transport, trusted clocks, hardware identity, or mutation authority.

## Structured receipt signature envelopes — 2026-09-26

The real local runner now signs the entire serialized receipt with HMAC-SHA256 and emits an `ndr.receipt-signature.v1` detached JSON envelope containing `algorithm`, non-secret `key_id`, `receipt_sha256`, and `signature`. Production/local deployments should keep concrete account names, key IDs, fingerprints, and custody metadata outside public repository fixtures and documentation.

ACP validates the envelope schema, algorithm, exact receipt SHA-256, key ID, and HMAC before accepting integrity. Any receipt-byte change fails verification. Focused adapter coverage: 16 passed, 1 skipped. Full ACP regression: 572 passed, 5 skipped. Real envelope conformance passed locally.

Boundary: HMAC proves possession of the same local secret, not independent identity. It is not TPM/hardware-rooted attestation, not remote endpoint authentication, and not external trust.

## Request-side side-effect binding + bounded TTL — 2026-09-26

The candidate request now carries `expected_side_effect_class` and receipt matching fails closed if the executor reports a different class. Signed request canonicalization includes this expected class. Freshness envelopes are capped at 300 seconds; longer TTLs are rejected before execution admission.

Focused adapter coverage: 18 passed, 1 skipped. Full ACP regression: 574 passed, 5 skipped. A real `READ_ONLY_DISCOVERY` / `READ_ONLY` receipt passed the updated request↔receipt conformance check.

## Device binding, local ordering, and signed pre-execution requests — 2026-09-26

The real runner now emits a privacy-preserving SHA-256 device fingerprint derived from stable system/firmware facts while retaining no raw identifiers in the identity record. The observed attestation level is explicitly `SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED`; TPM and Secure Boot state are not observable from the current non-elevated RDC context and are therefore not inferred.

ACP requests now bind expected device fingerprint and expected attestation level. Drift in either field fails closed. Focused adapter coverage reached 23 passed / 1 skipped; full ACP regression reached 579 passed / 5 skipped.

Receipts also carry a durable monotonically increasing local sequence number, backward-clock detection, and `trusted_time_established=false`. Consecutive real receipts were sequence 3 then 4 with no rollback detected. Windows Time was observed stopped/manual, so trusted time remains NOT_ESTABLISHED.

A signed read-only pre-execution envelope path is operational locally. The envelope binds request ID, device identity, attestation level, profile, expected side-effect class, exact command digest, working directory, nonce, and bounded freshness. The executor verifies the signature, device binding, TTL, and durable replay guard before execution. A valid read-only envelope executed and retained the exact request envelope as a hashed receipt artifact. Replaying the same envelope returns `REMOTE_REQUEST_FAIL: remote execution request replay detected` and `SIGNED_REMOTE_EXECUTION=BLOCKED`. Correctly signed mutation-profile requests are also refused.

This remains local candidate evidence only. Hardware-rooted attestation, trusted external time, remote endpoint authentication, mutation authorization, independent validation, and High-Assurance remain unestablished.

## PR #91 audit hardening — 2026-09-26

A dedicated review pass found and corrected three contract gaps before review advancement:

1. `READ_ONLY_DISCOVERY` now fails closed if the receipt reports any non-empty `side_effects`, not only changed files.
2. All HMAC signing paths now require at least 32 bytes of key material; request, canonical-receipt, detached-file, and envelope verification use one minimum-strength rule.
3. ACP now verifies actual receipt-chain continuity: the current receipt must reference the SHA-256 of the exact previous receipt bytes and use the immediately subsequent sequence number.

Post-audit local verification: 28 focused tests passed / 1 skipped; full ACP regression 584 passed / 5 skipped.

## Signed-command allowlist hardening — 2026-09-26

A second PR review pass identified a critical semantic gap: a request could declare `READ_ONLY` while carrying an arbitrary shell command. The signed pre-execution path now rejects arbitrary shell content and admits only exact, pre-reviewed inspection commands from `READ_ONLY_COMMAND_ALLOWLIST`. Shell chaining/metacharacter variants and destructive commands are rejected even if the envelope is otherwise correctly signed.

This is intentionally narrow. Expanding the signed execution surface requires adding a reviewed operation to the allowlist with tests; callers cannot create new read-only capabilities by relabeling arbitrary commands.

## Public schema / portability cleanup — 2026-09-26

Public fixtures use synthetic device identities and fingerprints; deployment-specific hostnames, account names, key IDs, and stable machine fingerprints are intentionally excluded from repository examples. `device_id` is the canonical ACP field for both requests and receipts. Receipt parsing retains the legacy executor field `device` as a backward-compatible alias for existing evidence packets.

## Typed v2 execution contract — 2026-09-26

New signed execution requests now use the typed v2 contract documented in `docs/TYPED_REMOTE_EXECUTION.md`.

The active issuance path carries an operation ID plus operation-specific structured parameters rather than `command_or_action`. ACP derives fixed argv from an immutable registry, resolves the requested working directory against executor-configured allowed roots, consumes replay only after deterministic admission checks, and executes with `shell=False` under bounded runtime/output limits.

The v1 shell-text request format is retained only for historical evidence compatibility. New legacy request signing is disabled by default; historical signature verification uses an explicit internal compatibility override. Remote mutation remains outside this contract.
