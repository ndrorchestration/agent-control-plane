# Authority Partition Simulation

**Status:** deterministic local experiment harness; not a network implementation.

This harness exercises ACP authority-state freshness behavior under synthetic node divergence. It models nodes with independent in-memory authority-state caches and evaluates each node against the same explicit freshness requirement.

It is intended to answer a narrow question: **does a node fail closed when its locally cached authority state is missing, too old, or below a known epoch floor?**

It does not model packet transport, Reticulum, consensus, clocks under adversarial drift, Byzantine behavior, cryptographic identity, revocation propagation latency, or real partition healing.

A disconnected node cannot prove that its state is globally latest. The harness therefore relies on externally supplied safety bounds: a known minimum epoch and/or a maximum acceptable snapshot age.
