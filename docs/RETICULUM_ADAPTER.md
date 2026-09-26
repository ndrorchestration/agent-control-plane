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


## Authority-sync watermark carriage

ACP's synchronization watermark protocol is carried on a separate fixed Reticulum request path:

`/ndrorchestration/acp/authority-sync-watermark/v0`

The Reticulum adapter does not decide whether a watermark issuer is trusted or what floor should govern execution. Those decisions remain inside `AuthoritySyncWatermarkRegistry` and `AuthoritySyncProgressGuard`.

When watermark peer binding is configured, `ReticulumAuthoritySyncWatermarkServer` decodes only enough of the canonical ACP watermark to bind its claimed `issuer_id` to the Reticulum `remote_identity` hash before handing the payload to the ACP watermark endpoint. The client-side watermark transport inherits the same outbound ACP peer-ID → Reticulum destination-hash check used by ordinary authority sync.

The live localhost gate exercises one identified Reticulum client sending a watermark for its authority-sync stream, verifies `APPLIED`, then resends the exact watermark and requires `DUPLICATE`.

The live integration now also uses `DurableAuthoritySyncWatermarkRegistry` and reuses the same watermark database after terminating and restarting the Reticulum server process. The exact pre-restart watermark must then return `DUPLICATE`, demonstrating that the accepted watermark floor and identity survive the process restart in the tested configuration.\n\nThis remains bounded local evidence only. It is not multi-peer dissemination, quorum agreement, global completeness, secure trust provisioning, cryptographic watermark authentication, or proof that the SQLite database cannot be maliciously rewritten.


## Authenticated single-relay watermark carriage

ACP now has a separate one-hop relay path candidate:

`/ndrorchestration/acp/authority-sync-watermark-relay/v0`

`ReticulumRelayedWatermarkServer` binds the relay envelope's declared `relay_id` to the Reticulum `remote_identity` hash before passing the bytes into the ACP relay endpoint. The relay endpoint then independently verifies the embedded origin-authenticated watermark and applies only the original watermark to the trusted monotonic registry.

This deliberately separates two identities:

- **relay identity** — bound by the Reticulum link;
- **origin watermark issuer** — verified by the embedded authenticated-watermark profile.

The relay does not become the origin merely by transporting the record.

This is still one-hop adapter evidence only. It does not establish a multi-hop relay chain, relay-path signatures, origin-key provisioning, asymmetric signatures, compromised-relay resistance, or global completeness.


## Bounded Reticulum transport-node topology

A separate multi-hop integration candidate uses three isolated local Reticulum instances:

`ACP client -> transport-enabled Reticulum node -> ACP destination`

The middle process enables Reticulum transport and exposes one gateway-mode TCP server. Both edge instances connect to that transport node as TCP clients, matching Reticulum's documented same-host gateway pattern. The client has no direct interface to the destination. The destination continues to bind the ACP sender ID to the client's identified Reticulum identity, so the intermediate Reticulum transport node does not become the ACP application sender.

The test requires:
- discovery/path availability for the destination through the transport node;
- link establishment from the client to the final destination;
- one canonical ACP authority snapshot to return `APPLIED`;
- exact replay over the same routed path to return `DUPLICATE`.

A green result would establish only bounded localhost Reticulum routing across one transport-enabled intermediate node under pinned `rns==1.5.4`. It would not establish arbitrary Internet/radio topology behavior, route resilience, partition healing, LoRa performance, long-duration liveness, or the signed ACP relay-chain protocol traversing that topology.


## Signed relay-chain composition over routed Reticulum

The routed localhost topology gate now also has a candidate composition path for the accepted Ed25519 relay-chain profile.

A complete signed origin + three-hop relay chain is encoded by ACP and sent to the final ACP destination over the same verified Reticulum route that traverses the transport-enabled intermediate node. The destination's Reticulum handler binds the currently identified remote peer to the terminal signed relay ID, then the ACP endpoint independently verifies the origin signature, every hash-linked relay-hop signature, relay-key lifecycle, hop ordering, and final-receiver binding before applying the origin watermark.

The first composition slice deliberately constructs the signed relay chain in the sending test process. Therefore a green result establishes that signed ACP relay provenance survives routed Reticulum carriage and is enforced at the final receiver. It does **not** establish that separate application relay processes independently appended each hop. That remains a later test.


## Separate relay-process execution candidate

The routed signed relay-chain integration now has a stricter execution candidate: the origin process emits only the signed origin envelope, then three separate OS subprocesses execute relay A, relay B, and relay C in sequence.

Each relay subprocess:
1. decodes the chain state it receives;
2. verifies the signed origin;
3. if prior hops exist, verifies the complete incoming prefix is addressed to its own relay ID;
4. appends exactly one new Ed25519-signed hop naming the next receiver;
5. emits a new canonical chain payload.

Only the final chain payload is then sent across the verified routed Reticulum topology to the destination.

This establishes separate process execution boundaries for relay append operations under deterministic test fixtures. It does **not** establish secure private-key isolation, separate hosts, independent trust domains, or one Reticulum application destination per relay process.


## Live relay-stage endpoint candidate

ACP now also has a byte-facing relay-stage endpoint and a fixed Reticulum relay-stage request path. A relay stage derives the logical upstream sender from the signed chain prefix: the origin issuer for the first hop, or the prior relay ID for later hops. The Reticulum server binds that derived upstream ID to the currently identified remote Reticulum identity before allowing the stage to verify and append its hop.

This closes a narrower gap than the subprocess test: the append operation can now execute behind a Reticulum application endpoint rather than only through a local file handoff.

The candidate still does not establish a full live chain of separate Reticulum relay destinations forwarding autonomously. That remains the next integration step.


## Autonomous application relay-chain candidate

A stricter integration candidate now separates application forwarding from the test harness:

`origin -> relay-a -> relay-b -> relay-c -> destination`

Each relay is a distinct OS process and Reticulum destination. The origin sends the initial signed chain only to relay A. Each relay stage:

1. authenticates the current Reticulum upstream identity against the logical upstream derived from the signed chain prefix;
2. verifies that the chain prefix is cryptographically valid and addressed to that relay;
3. appends exactly one Ed25519-signed hop;
4. forwards the updated bytes over its own identified Reticulum link to the next stage;
5. returns the downstream final acknowledgement unchanged.

Relay C forwards the complete chain to the final ACP destination, where the origin signature, all relay-hop signatures, hash linkage, final-receiver binding, relay-key lifecycle, and terminal Reticulum identity are verified before applying the watermark.

The dedicated `reticulum-autonomous-relay-chain` workflow is the acceptance gate for this composition. Until that exact-head workflow is terminal green and merged, autonomous multi-stage forwarding remains NOT ESTABLISHED.

Even after a green localhost run, this remains bounded evidence. Separate physical hosts, independent administrative trust domains, key custody, route failover, partition healing, radio/LoRa, Byzantine behavior, and production security remain outside the claim.


## Relay outage / identity-preserving recovery candidate

The autonomous relay-chain harness now contains an additional failure/recovery phase.

After an initial `APPLIED` and exact `DUPLICATE` result, relay B is terminated while the origin, relay A and final destination remain live. A new higher-sequence origin watermark is then sent through relay A. The request must fail closed and must not produce an accepted acknowledgement while the application chain is incomplete.

The origin-facing link and remaining relay processes are then torn down, and relay A/B/C are restarted using the exact same provisioned Reticulum identity files. The final destination remains live and retains its previously accepted watermark state. Recovery requires:

- relay A/B/C destination hashes to remain unchanged after restart;
- recovered relay A to drain exactly one pending forward before readiness;
- the origin's resend of that higher-sequence watermark to return `DUPLICATE`, proving the queued forward already reached the destination during startup drain;
- exact replay after recovery to remain `DUPLICATE`.

This is explicit restart/reconnect recovery, not automatic self-healing. A green run does not establish transparent link re-establishment, process supervision, retry orchestration, partition healing, durable relay queues, or delivery guarantees.


## Durable pending relay-forward queue candidate

Each autonomous relay stage can now use a local SQLite-backed pending-forward queue.

The forwarding sequence is intentionally fail-safe:

1. verify the incoming signed prefix and append exactly one signed hop;
2. persist the resulting canonical relay-chain bytes and SHA-256 identity locally;
3. record the downstream send attempt;
4. perform the downstream exchange;
5. delete the pending record only after a byte response is returned.

If downstream exchange fails, the pending record remains in SQLite with its attempt count. Reopening the queue after process restart reconstructs the pending set, and the relay stage can drain those records through its configured downstream exchange before advertising readiness for new inbound work.

The queue manifest exposes identifiers, hashes, timestamps and attempt counts, but not queued payload bytes.

This establishes local durable pending-forward state and explicit replay mechanics only. It does not establish exactly-once delivery, globally unique delivery, transactional coupling to Reticulum, crash safety at every filesystem boundary, guaranteed delivery, bounded retry/backoff, dead-letter handling, remote acknowledgement durability, or production message-queue semantics.


## Deterministic bounded relay retry policy

ACP now has a scheduler-neutral retry primitive for durable pending relay forwards.

`BoundedRelayRetryPolicy` defines:
- maximum attempts;
- base delay;
- exponential multiplier;
- maximum delay cap;
- due-time calculation from the durable queue's last-attempt timestamp.

`RetryingRelayForwarder.sweep(now=...)` performs at most one retry decision per pending item and returns explicit outcomes: `delivered`, `deferred`, `failed`, or `exhausted`. Failed attempts remain pending. Exhausted items remain pending rather than being silently dropped.

The policy does not sleep, spawn workers, schedule future work, or move exhausted records into a dead-letter store. A caller or future supervisor must invoke sweeps. Therefore this establishes deterministic retry/backoff semantics only—not automatic retries, process supervision, guaranteed delivery, dead-letter handling, or production queue orchestration.


## Durable relay dead-letter candidate

Policy-exhausted pending relay forwards can now be moved into a separate SQLite-backed dead-letter store.

Movement is intentionally evidence-preserving:
1. read the pending record;
2. persist its payload, payload hash, relay/downstream IDs, enqueue/attempt timestamps, terminal attempt count, and reason in the dead-letter store;
3. only after successful dead-letter persistence, remove the pending record.

The dead-letter ID is deterministic from the relay/downstream/payload/item identity, and repeat storage of the same terminal record is idempotent. Conflicting terminal records fail closed.

`dead_letter_exhausted(...)` consults the accepted `BoundedRelayRetryPolicy` and moves only items whose durable attempt count has reached the configured maximum. Retryable records remain pending.

This establishes terminal local storage semantics only. It does not establish operator notification, re-drive workflows, retention policy, deletion policy, queue quotas, external alerting, guaranteed delivery, or production dead-letter infrastructure.


## Bounded local relay-queue capacity

The durable pending relay-forward queue can now be configured with optional maximum pending-item and pending-byte limits.

Admission is fail-closed for a **new** item that would exceed either configured limit. The capacity check and insert occur under a SQLite `BEGIN IMMEDIATE` transaction so concurrent enqueue attempts cannot both pass the same stale usage snapshot. Re-enqueuing the exact same already-pending item remains idempotent even when the queue is otherwise at capacity. Acknowledgement or dead-letter movement releases pending capacity.

The queue exposes current pending item/byte usage and configured limits through its manifest without including payload bytes.

These controls provide local storage backpressure only. They do not establish network congestion control, sender-side flow-control signaling, fairness, priority scheduling, disk-space guarantees, denial-of-service resistance, or production queue sizing.


## Deterministic relay supervision cycle

ACP now has a caller-driven supervisory maintenance primitive that composes the accepted durable queue, bounded retry policy, and dead-letter store.

A `RelaySupervisorCycle.run(now=...)` call:
1. performs one bounded retry sweep over pending records;
2. moves only retry-policy-exhausted records into durable dead-letter state;
3. samples remaining queue usage and total dead-letter count;
4. reports a deterministic health state:
   - `idle`: no work;
   - `healthy`: retry work completed with no pending/degraded state;
   - `degraded`: deferred/failed/retryable work remains;
   - `blocked`: an item exhausted and was dead-lettered.

The cycle does not schedule itself, sleep, restart relay processes, supervise OS PIDs, or create background workers. It is orchestration logic for a future supervisor, not evidence of an automatic supervisory runtime.
