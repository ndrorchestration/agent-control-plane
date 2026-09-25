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

The candidate does **not** initialise `RNS.Reticulum`, discover peers, create destinations, establish links, announce destinations, authenticate remote identities, choose `ALLOW_*` policy, or manage Reticulum configuration.

Those responsibilities remain external because:

1. ACP should not silently decide network topology or trust policy.
2. Reticulum identity/link setup has security and operational implications that need an explicit integration contract.
3. The current CI environment verifies adapter semantics with test doubles, not a real RNS runtime.

The server binding accepts the Reticulum `allow` value as an explicit caller argument. Production-like use should not default silently to permissive `ALLOW_ALL`; peer-identity policy must be chosen and verified by the integration.

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
