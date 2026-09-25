# Experimental Reticulum Authority-Sync Adapter

> **Status:** implementation candidate / offline conformance only.
>
> **Reticulum compatibility is NOT yet established by a live network run.**

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
| Canonical acknowledgement bytes | request-handler return value |
| Peer/link lookup | caller-supplied `peer_links` mapping |

The fixed request path is:

`/ndrorchestration/acp/authority-sync/v0`

## Deliberate boundaries

The candidate does **not** initialise `RNS.Reticulum`, discover peers, create destinations, establish links, announce destinations, choose application trust policy, or manage Reticulum configuration.

Those responsibilities remain external because:

1. ACP should not silently decide network topology or trust policy.
2. Reticulum identity/link setup has security and operational implications that need an explicit integration contract.
3. The current CI environment verifies adapter semantics with test doubles, not a real RNS runtime.

The server binding accepts the Reticulum `allow` value as an explicit caller argument. Production-like use should not default silently to permissive `ALLOW_ALL`.

When `peer_identity_hashes` is configured, the server additionally binds each claimed ACP sync `sender_id` to an expected Reticulum identity hash. The handler requires Reticulum to supply a `remote_identity`, extracts its identity hash, and rejects unknown sender IDs, missing identities, unavailable hashes, and hash mismatches before ACP reconciliation.

For this to work, the initiating Reticulum peer must identify over the established link (for example with `Link.identify(identity)`). Reticulum documents this mechanism as revealing the initiator identity to the remote peer over the encrypted link and allowing it to be used for authentication. The live integration gate also uses `Destination.ALLOW_LIST` with the same expected identity hash.

## Evidence ceiling

Current tests establish only that the adapter:

- calls the documented request method shape;
- registers the documented request-handler shape;
- carries canonical ACP request/acknowledgement bytes;
- fails closed for unknown peers, unsent requests, local timeout, non-byte responses, double handler installation, wrong request paths, and malformed payload types.

They do not establish:

- installation/runtime compatibility with a particular `rns` package release;
- real link establishment or path discovery;
- Reticulum delivery reliability;
- remote identity authentication;
- confidentiality beyond what a correctly configured Reticulum link would provide;
- resilience over LoRa/radio/IP or disrupted networks;
- end-to-end partition/revocation propagation;
- Reticulum security certification.

## Next verification gate

A separate live-integration slice should install the current supported `rns` package, create two isolated local Reticulum instances/configurations, establish a link, register the ACP request handler, exchange one canonical snapshot and one revocation, and capture exact runtime/version/result evidence.

## Identity-binding evidence boundary

A successful local live test can establish that the pinned Reticulum runtime supplied an identified peer identity whose hash matched the ACP sender binding and that `ALLOW_LIST` permitted the request.

It does not establish:

- that an identity is owned by a real-world person or organization;
- PKI, certificate-chain, account, device, or hardware identity;
- revocation of Reticulum identities themselves;
- secure provisioning of the sender-ID → identity-hash binding;
- resistance to compromise of the corresponding private identity keys;
- trust equivalence between a Reticulum identity and DGAF authorization.
