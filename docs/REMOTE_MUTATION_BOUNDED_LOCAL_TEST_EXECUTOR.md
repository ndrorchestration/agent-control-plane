# ACP bounded local-test mutation executor

Status: **CANDIDATE / DISPOSABLE-REPOSITORY ONLY / REAL-PROJECT MUTATION NOT AUTHORIZED**

This document defines the implementation boundary for issue #154.

## Accepted profile

The executor is intentionally limited to the `BOUNDED_LOCAL_TEST` residual-risk profile selected by PR #149.

It may be exercised only against synthetic or disposable repositories created for testing. It does not authorize ACP, DGAF, Aetherwake, or any other real project repository as a mutation target.

## Mechanical scope controls

Construction requires:

- `experimental_enable=True`;
- an exact absolute repository-root allowlist;
- a `.git` marker;
- an explicit `.acp-disposable-test-repository` file whose exact content is `ACP_DISPOSABLE_TEST_ONLY\n`.

The disposable marker is a scope declaration, not a security boundary. It prevents ordinary project checkouts from qualifying by default but does not establish hostile-local-actor resistance.

The executor exposes only the existing mutation registry operations:

- `repo.write_text_file`;
- `repo.delete_file`.

There is no shell, argv, arbitrary process, recursive delete, chmod, rename, or Git-metadata mutation surface.

## Governed execution sequence

A bounded test mutation follows the current-main control chain:

`admission -> exact plan -> path safety -> rollback custody -> journal PREPARED -> single-use execution authorization -> authorization consumption -> execution intent -> side effect -> effect evidence -> postcondition verification -> evidence binding -> closure`

Pre-consumption validation failures do not consume authorization.

After execution intent, failures enter the journal failure/recovery path and do not silently retry or auto-rollback.

## Authority non-transfer

A successful executor result fixes:

- `authority_effect=NONE`;
- `follow_on_authority=FRESH_ADJUDICATION_REQUIRED`;
- `bounded_local_test_only=true`.

The consumed authorization cannot authorize a second effect. A later consequential mutation requires a fresh admission/adjudication path and a distinct current authorization.

For explicitly chained execution, ACP now uses a typed follow-on binding that requires:
- the prior execution closure to be terminal and non-authorizing;
- the prior evidence digest to be preserved;
- a fresh admitted mutation record with decision and policy identity;
- a distinct request identity;
- a distinct, unconsumed current execution authorization;
- exact admission/authorization identity agreement.

The bounded executor fails closed when a prior closure is supplied without that fresh-adjudication binding.

This mechanism does **not** claim a global resource/effect lineage oracle. If a caller hides prior execution lineage entirely, this local executor cannot infer that omitted history from the invocation alone. A future stronger profile would require durable cross-invocation resource/effect lineage outside this bounded tranche.

Rollback remains separately authorized; forward execution does not grant rollback authority.

## Retained ceilings

This candidate does not establish:

- `FINAL_PATH_TO_SYSCALL_TOCTOU=ELIMINATED`;
- hostile-local-actor resistance;
- trusted process identity;
- peer-process tamper resistance;
- High-Assurance process isolation;
- real-project repository mutation authority;
- production executor status;
- rollback execution;
- independent validation;
- High-Assurance.

A successful current-main rebuild may establish only:

`BOUNDED_LOCAL_TEST_EXECUTOR=ESTABLISHED_FOR_TESTED_DISPOSABLE_SCOPE`

and only after exact-head tests and hosted integration checks support that bounded classification.
