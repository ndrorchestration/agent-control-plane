# Experimental Reticulum Authority-Sync Adapter

> **Status:** experimental adapter with bounded localhost live-integration evidence.
>
> **Established only for the pinned CI configuration:** real `rns==1.5.4` localhost TCP link exchange, inbound/outbound identity binding, canonical snapshot/revocation exchange, replay protection across relink, and durable reconciliation recovery across a Reticulum server process restart.

ACP's first Reticulum adapter candidate maps the transport-neutral authority-sync contract onto Reticulum's documented request/response surface.

Current upstream API references used for this candidate:

- `RNS.Destination.register_request_handler(path, response_generator=..., allow=..., allowed_list=..., auto_compress=...)` for the receiving endpoint;
- `RNS.Link.request(path, data=..., timeout=..., max_response_size=...)` for the sending side;
- `RNS.RequestReceipt.concluded()` and `get_response()` for bounded request completion.

## ACP mapping

| ACP responsibility | Reticulum-facing candidate |
| --- | --- |
| Canonical sync request bytes | `Link.request(..., data=payload)` |
| Server receive boundary | `Destination.register_request_handler(...)` |
| ACP schema/replay/epoch/revocation reconciliation | `AuthoritySyncEndpoint` / `AuthoritySyncReconciler` |
| Durable applied-message recovery | `DurableAuthoritySyncReconciler` / SQLite append-only canonical log |
| Canonical acknowledgement bytes | request-handler return value |
| Peer/link lookup | caller-supplied `peer_links` mapping |

The fixed request path is:

`/ndrorchestration/acp/authority-sync/v0`

## Deliberate boundaries

The reusable adapter itself does **not** initialise `RNS.Reticulum`, discover peers, create destinations, establish links, announce destinations, choose application trust policy, or manage Reticulum configuration. The dedicated integration harness performs those actions only to exercise the adapter in a bounded localhost test topology.

Those responsibilities remain external because:

1. ACP should not silently decide network topology or trust policy.
2. Reticulum identity/link setup has security and operational implications that need an explicit integration contract.
3. The current CI environment verifies adapter semantics with test doubles, not a real RNS runtime.

The server binding accepts the Reticulum `allow` value as an explicit caller argument. Production-like use should not default silently to permissive `ALLOW_ALL`.

When `peer_identity_hashes` is configured, the server additionally binds each claimed ACP sync `sender_id` to an expected Reticulum identity hash. The handler requires Reticulum to supply a `remote_identity`, extracts its identity hash, and rejects unknown sender IDs, missing identities, unavailable hashes, and hash mismatches before ACP reconciliation.

On the initiating side, `peer_destination_hashes` can bind each ACP outbound `peer_id` to the expected Reticulum destination hash. Before issuing a request, the adapter reads the established Link's destination hash and rejects a missing, unavailable, or mismatched destination. This prevents an ACP peer label from silently being remapped to a different Reticulum destination object.

For this to work, the initiating Reticulum peer must identify over the established link (for example with `Link.identify(identity)`). Reticulum documents this mechanism as revealing the initiator identity to the remote peer over the encrypted link and allowing it to be used for authentication. The live integration gate also uses `Destination.ALLOW_LIST` with the same expected identity hash.

## Evidence ceiling

Current tests establish that the adapter:

- calls the documented request method shape;
- registers the documented request-handler shape;
- carries canonical ACP request/acknowledgement bytes;
- fails closed for unknown peers, unsent requests, local timeout, non-byte responses, double handler installation, wrong request paths, and malformed payload types;
- exchanges canonical ACP snapshot and revocation records over a real pinned `rns==1.5.4` localhost TCP link;
- binds the inbound ACP sender ID to the identified Reticulum client identity hash;
- binds the outbound ACP peer ID to the discovered server destination hash;
- preserves duplicate/replay semantics across Reticulum link teardown and re-establishment;
- persists canonically applied sync messages to SQLite and reconstructs snapshot, revocation, duplicate, and sender-sequence state after the Reticulum server process is terminated and restarted.

They do not establish:

- compatibility with arbitrary Reticulum releases/configurations;
- Reticulum delivery reliability outside the tested localhost TCP topology;
- secure real-world provisioning or ownership of identity/destination bindings;
- protection from private-key compromise;
- resilience over LoRa/radio, multi-hop paths, Internet-scale routing, or long-duration disrupted networks;
- bounded revocation propagation latency during partitions;
- multi-process concurrent-writer correctness for the SQLite reconciliation log;
- cryptographic integrity of the local persistence database;
- global authority freshness or consensus;
- Reticulum security certification or production readiness.

## Next verification gate

The next high-value gate is deterministic partition/reconnect testing around the durable authority-sync state: delay newer authority/revocation messages while a node is isolated, enforce explicit freshness bounds locally, reconnect, reconcile the newer state, and verify that stale authority cannot regain execution eligibility during or after recovery. Multi-hop/radio testing remains a later and separate evidence class.

## Identity-binding evidence boundary

A successful local live test can establish that the pinned Reticulum runtime supplied an identified peer identity whose hash matched the ACP sender binding and that `ALLOW_LIST` permitted the request.

It does not establish:

- that an identity is owned by a real-world person or organization;
- PKI, certificate-chain, account, device, or hardware identity;
- revocation of Reticulum identities themselves;
- secure provisioning of the sender-ID → identity-hash binding;
- resistance to compromise of the corresponding private identity keys;
- trust equivalence between a Reticulum identity and DGAF authorization.
