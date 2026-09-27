"""Read-only postcondition verification for externally performed repository mutations.

ACP does not perform the mutation in this tranche. This module observes the
current repository state and verifies it against the exact admitted plan.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Union

from .remote_mutation_path_safety import MutationPathSafetyRecord
from .remote_mutation_rollback_custody import RollbackCustodyAdmissionRecord
from .remote_mutation_transaction import MutationPlan

MUTATION_POSTCONDITION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-postcondition.v0-candidate"
)


class MutationPostconditionError(ValueError):
    pass


def _sha256(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise MutationPostconditionError(f"{field_name} must be lowercase sha256")
    return value


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class MutationPostconditionRecord:
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    requested_path: str
    repository_root: str
    resolved_path: str
    target_exists: bool
    observed_content_sha256: str | None
    path_revalidated: bool
    postcondition_verified: bool
    reason: str
    execution_enabled: bool = False
    acp_mutation_executed: bool = False
    schema_version: str = MUTATION_POSTCONDITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _sha256(self.plan_sha256, "plan_sha256")
        if self.observed_content_sha256 is not None:
            _sha256(self.observed_content_sha256, "observed_content_sha256")
        if self.execution_enabled is not False or self.acp_mutation_executed is not False:
            raise MutationPostconditionError(
                "postcondition verification cannot enable or claim ACP mutation execution"
            )
        if self.postcondition_verified and self.path_revalidated is not True:
            raise MutationPostconditionError(
                "verified postcondition requires path revalidation"
            )


def verify_repository_mutation_postcondition(
    plan: MutationPlan,
    path_safety: MutationPathSafetyRecord,
    rollback_custody: RollbackCustodyAdmissionRecord,
    *,
    repository_root: Union[str, Path],
) -> MutationPostconditionRecord:
    """Observe current state for the exact plan; never mutate repository state."""
    if not isinstance(plan, MutationPlan):
        raise TypeError("plan must be MutationPlan")
    if not isinstance(path_safety, MutationPathSafetyRecord):
        raise TypeError("path_safety must be MutationPathSafetyRecord")
    if not isinstance(rollback_custody, RollbackCustodyAdmissionRecord):
        raise TypeError("rollback_custody must be RollbackCustodyAdmissionRecord")

    if path_safety.execution_enabled is not False or path_safety.mutation_executed is not False:
        raise MutationPostconditionError(
            "path safety unexpectedly enables or claims mutation execution"
        )
    if (
        rollback_custody.execution_enabled is not False
        or rollback_custody.mutation_executed is not False
    ):
        raise MutationPostconditionError(
            "rollback custody unexpectedly enables or claims mutation execution"
        )

    mismatches: list[str] = []
    if (
        path_safety.admitted is not True
        or path_safety.request_id != plan.request_id
        or path_safety.resource_id != plan.resource_id
        or path_safety.operation_id != plan.operation_id
        or path_safety.plan_sha256 != plan.plan_sha256
        or path_safety.requested_path != plan.parameters["path"]
    ):
        mismatches.append("path_safety")

    if (
        rollback_custody.admitted is not True
        or rollback_custody.request_id != plan.request_id
        or rollback_custody.resource_id != plan.resource_id
        or rollback_custody.operation_id != plan.operation_id
        or rollback_custody.plan_sha256 != plan.plan_sha256
        or rollback_custody.descriptor_sha256 != plan.rollback_sha256
        or rollback_custody.readback_verified is not True
    ):
        mismatches.append("rollback_custody")

    root = Path(repository_root)
    if not root.is_absolute():
        raise MutationPostconditionError("repository_root must be absolute")
    root_valid = root.exists() and root.is_dir() and (root / ".git").exists()
    if not root_valid:
        mismatches.append("repository_root")

    requested_path = plan.parameters["path"]
    target = root.joinpath(*requested_path.split("/"))

    resolved_root = root.resolve(strict=True) if root.exists() else root
    resolved_target = target.resolve(strict=False)
    boundary_ok = (
        resolved_target != resolved_root
        and resolved_target.is_relative_to(resolved_root)
    )

    cursor = root
    ancestors = [root]
    for part in requested_path.split("/")[:-1]:
        cursor = cursor / part
        ancestors.append(cursor)
    ancestor_symlink = any(p.is_symlink() for p in ancestors if p.exists())
    target_symlink = target.is_symlink()
    path_revalidated = root_valid and boundary_ok and not ancestor_symlink and not target_symlink
    if not path_revalidated:
        mismatches.append("path_revalidation")

    target_exists = target.exists()
    observed_content_sha256: str | None = None
    operation_verified = False

    if plan.operation_id == "repo.write_text_file":
        if target_exists and target.is_file() and not target_symlink:
            observed_content_sha256 = _hash_file(target)
            operation_verified = (
                observed_content_sha256 == plan.parameters["content_sha256"]
            )
        if not operation_verified:
            mismatches.append("write_postcondition")
    elif plan.operation_id == "repo.delete_file":
        operation_verified = not target_exists
        if not operation_verified:
            if target.is_file() and not target_symlink:
                observed_content_sha256 = _hash_file(target)
            mismatches.append("delete_postcondition")
    else:
        mismatches.append("operation_id")

    verified = not mismatches
    reason = (
        "exact repository mutation postcondition verified; ACP execution remains disabled"
        if verified
        else "postcondition blocked:" + ",".join(mismatches)
    )

    return MutationPostconditionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=requested_path,
        repository_root=str(root),
        resolved_path=str(resolved_target),
        target_exists=target_exists,
        observed_content_sha256=observed_content_sha256,
        path_revalidated=path_revalidated,
        postcondition_verified=verified,
        reason=reason,
    )