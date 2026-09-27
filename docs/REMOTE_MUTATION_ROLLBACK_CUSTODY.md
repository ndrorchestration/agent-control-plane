# Remote Mutation Rollback Custody

Status: **NON-EXECUTING / CUSTODY-EVIDENCE ADMISSION ONLY**.

This tranche follows exact authority/plan composition and repository path safety.
It defines what rollback material must exist for the exact planned operation and
requires caller-observed custody/read-back identity before the mutation stack may
advance. ACP does not write custody material in this tranche.

## Rollback descriptor

A deterministic `RollbackMaterialDescriptor` binds:

- exact operation ID;
- exact repository-relative path;
- rollback mode;
- prior content SHA-256 and byte size when prior bytes must be restored.

Supported modes:

- `restore_file_bytes` — restore exact prior bytes;
- `delete_created_file` — remove a file that did not exist before the planned write.

Rules:

- existing `repo.write_text_file` target -> `restore_file_bytes`;
- new `repo.write_text_file` target -> `delete_created_file`;
- `repo.delete_file` -> `restore_file_bytes`, and descriptor prior-content hash
  must equal the plan's `prior_content_sha256`.

The descriptor is canonically serialized and hashed. Its SHA-256 must equal
`MutationPlan.rollback_sha256`.

## Custody evidence

`RollbackCustodyEvidence` binds the exact request/resource/operation/plan,
descriptor SHA-256, an opaque caller-provided custody reference, the expected
custody-object SHA-256, and an observed read-back SHA-256.

For `restore_file_bytes`, the custody-object SHA-256 must equal the descriptor's
prior-content SHA-256.

For `delete_created_file`, no prior bytes exist; the custody object is the
canonical rollback descriptor itself, so its identity is the descriptor SHA-256.

The observed read-back SHA-256 must equal the custody-object SHA-256.

## Upstream requirements

Admission also requires:

- admitted exact mutation composition;
- prepared transaction with verified preconditions and rollback identity;
- admitted path-safety record bound to the exact plan;
- path-safety `target_exists` consistent with the rollback mode.

Any mismatch produces a blocked custody record.

## Strong non-effects

Every custody admission record fixes:

- `execution_enabled=false`
- `mutation_executed=false`

This layer does not create custody objects, write files, delete files, execute
rollback, or authorize mutation execution.

## Known boundaries

The custody reference and read-back hash are caller-provided evidence. This
candidate does not establish storage authenticity, encryption, immutability,
WORM retention, independent attestation, external custody, rollback execution,
postcondition verification, crash/interruption recovery, or production security.
