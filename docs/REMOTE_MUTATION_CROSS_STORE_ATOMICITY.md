# Remote Mutation Cross-Store Atomicity Decision

Status: **DESIGN DECISION / NON-AUTHORIZING**.

## Question

Must authorization consumption and mutation-journal intent be committed atomically in one durable transaction for the current bounded executor to fail closed?

## Decision

**No for current fail-closed safety; yes for stronger exactly-once / linearizable semantics.**

The executor consumes the single-use authorization before appending journal execution intent, and performs no repository side effect until after intent is durable. The cross-store recovery assessor therefore treats persisted states as follows:

- authorization unconsumed + journal PREPARED: no effect may exist; recovery still requires a fresh authorization;
- authorization consumed + journal PREPARED: crash occurred before durable intent; no executor side effect may exist; fresh authorization required;
- authorization consumed + journal at/after EXECUTION_INTENT_RECORDED: effect may exist until terminal evidence resolves it;
- authorization unconsumed + journal beyond PREPARED: impossible under the intended ordering; fail-closed operator hold;
- any identity mismatch across stores: fail-closed operator hold.

Because the ambiguous coordination window occurs before the first side-effect primitive, it is recoverable without guessing whether a repository effect happened.

## What this does not prove

- exactly-once execution;
- linearizability across the two SQLite databases;
- resistance to direct database tampering;
- safety if future code performs a side effect before journal intent;
- safety if another executor implementation changes the ordering.

Any change to the ordering must reopen this decision.