# Executor Process Identity Preflight

Status: **READ-ONLY / SELF-REPORTED LOCAL EVIDENCE / NON-AUTHORIZING**.

## Purpose

This tranche records the interpreter path/hash, local username, PID, platform, and executor ID observed by the current ACP process and compares them with an explicit allow policy.

It is intended to catch accidental execution under the wrong interpreter, executable build, local user, or executor identity before a live executor is invoked.

## Evidence level

The record is deliberately labeled:

`SELF_REPORTED_LOCAL`

That label is a hard invariant. The record is **not** cryptographic process attestation, code signing, TPM-backed identity, or an OS-enforced trust boundary.

Every record fixes:

`execution_authorized=false`

`mutation_executed=false`

## Current Windows environment finding

The current ACP development repository is writable by the same local account used by the RDC execution context. The installed Python executable is readable/executable by ordinary local users. Therefore a peer process running with equivalent local permissions could bypass ACP and mutate the repository or local SQLite stores directly.

Application-level executor IDs and executable hashes reduce accidental drift but do not prevent such bypass.

## Required stronger boundary before High-Assurance

Issue #118 remains responsible for evaluating and, if appropriate, implementing:

- a trusted launcher or signed/attested executable boundary;
- a least-privilege service/account identity;
- ACL separation between executor identity, repository roots, journal/authorization stores, and rollback custody;
- sandbox / Windows Job Object / AppContainer or equivalent restrictions where appropriate;
- protection against direct store tampering by peer processes;
- deployment-specific acceptance tests.

## Scope boundary

This preflight performs no repository mutation, no authorization issuance/consumption, and no external process launch. It is evidence for a future execution gate, not that gate itself.
