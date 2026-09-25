# Authority Partition Simulation

**Status:** deterministic local experiment harness; not a network implementation.

This harness exercises ACP authority-state freshness behavior under synthetic node divergence. It models nodes with independent in-memory authority-state caches and evaluates each node against the same explicit freshness requirement.

It is intended to answer a narrow question: **does a node fail closed when its locally cached authority state is missing, too old, or below a known epoch floor?**

It does not model packet transport, Reticulum, consensus, clocks under adversarial drift, Byzantine behavior, cryptographic identity, revocation propagation latency, or real partition healing.

A disconnected node cannot prove that its state is globally latest. The harness therefore relies on externally supplied safety bounds: a known minimum epoch and/or a maximum acceptable snapshot age.


## Durable reconnect safety extension

The authority-sync integration now has a separate fail-closed sync-progress guard. A reconnecting node can be configured with an externally known minimum sender sequence and remain ineligible even after receiving a newer authority snapshot until that sequence floor has been reconciled. This covers the case where a later revocation is known to exist but may still be delayed in transit.

The accompanying tests exercise this sequence:

1. local snapshot is too far behind the required sync floor → denied;
2. a newer snapshot arrives but the required floor is still unmet → denied;
3. the delayed revocation arrives and reaches the required floor → freshness gate clears, then the revocation check denies;
4. process restart reconstructs the same sequence floor and revocation state → still denied;
5. replay/regression cannot reduce or bypass the recovered floor.

The minimum sequence remains caller-supplied. This is not proof that the node has the globally newest state and does not solve consensus or unknown-message detection.
