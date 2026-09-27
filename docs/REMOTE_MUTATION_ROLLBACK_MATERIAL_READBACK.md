# Rollback Custody Material Readback Preflight

Status: **READ-ONLY / NON-EXECUTING / AUTHORIZATION NOT CONSUMED**.

This gate verifies material already retrieved from rollback custody against the exact rollback descriptor, rollback plan, and unconsumed rollback authorization.

For `restore_file_bytes`, caller-supplied bytes must match both the descriptor's prior-content SHA-256/size and the rollback plan's desired-content SHA-256.

For `delete_created_file`, no rollback material bytes are permitted or required.

A consumed authorization blocks admission. Successful readback does not consume the authorization.

## Strong non-effects

- no custody backend is trusted or authenticated by this module;
- no authorization is consumed;
- no rollback journal intent is appended;
- no repository file is written or deleted;
- `execution_enabled=false`;
- `rollback_executed=false`.

This closes the material-identity/readback portion of #119 while leaving the bounded rollback executor, rollback postcondition/evidence closure, and crash/restart side-effect tests separate.
