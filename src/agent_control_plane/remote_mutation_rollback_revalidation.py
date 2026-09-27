"""Read-only rollback path and current-state revalidation.

This module never performs rollback, retrieves custody bytes, or grants rollback
authority. It verifies that a RepositoryRollbackPlan still matches the observed
repository state closely enough for a later authorization gate to consider it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Union

from .remote_mutation_rollback_plan import RepositoryRollbackPlan

ROLLBACK_REVALIDATION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-revalidation.v0-candidate"
)

_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class RollbackRevalidationError(ValueError):
    pass


def _canonical_repo_path(value: str) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str) or not value:
        raise RollbackRevalidationError("rollback path must not be blank")
    if "\x00" in value or any(ord(ch) < 32 for ch in value):
        raise RollbackRevalidationError("rollback path contains control characters")
    if "\\" in value:
        raise RollbackRevalidationError("rollback path must use canonical '/' separators")
    if PurePosixPath(value).is_absolute() or value.startswith("/"):
        raise RollbackRevalidationError("rollback path must be repository-relative")
    if len(value) >= 2 and value[1] == ":" and value[0].isalpha():
        raise RollbackRevalidationError("rollback path must not be drive-qualified")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise RollbackRevalidationError("rollback path contains non-canonical segments")
    if PurePosixPath(value).as_posix() != value:
        raise RollbackRevalidationError("rollback path must be canonical")
    for part in parts:
        if ":" in part:
            raise RollbackRevalidationError("rollback path must not contain ':'")
        if part.startswith(" ") or part.endswith((" ", ".")):
            raise RollbackRevalidationError(
                "rollback path segment has ambiguous leading/trailing characters"
            )
        if part.split(".", 1)[0].lower() in _WINDOWS_RESERVED_BASENAMES:
            raise RollbackRevalidationError(
                "rollback path contains a reserved Windows device name"
            )
    return value, parts


def _is_reparse_point(path: Path) -> bool:
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT)


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or _is_reparse_point(path)


def _has_multiple_hardlinks(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        return os.stat(path, follow_symlinks=False).st_nlink > 1
    except OSError:
        return True


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class RepositoryRollbackRevalidationRecord:
    rollback_transaction_id: str
    rollback_plan_sha256: str
    resource_id: str
    requested_path: str
    repository_root: str
    resolved_path: str | None
    admitted: bool
    reason: str
    repository_boundary_verified: bool
    repository_metadata_safe: bool
    link_safe: bool
    hardlink_safe: bool
    operation_shape_verified: bool
    current_state_verified: bool
    observed_target_exists: bool
    observed_content_sha256: str | None
    execution_enabled: bool = False
    rollback_executed: bool = False
    schema_version: str = ROLLBACK_REVALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_enabled is not False or self.rollback_executed is not False:
            raise RollbackRevalidationError(
                "rollback revalidation cannot enable or claim rollback execution"
            )
        if self.admitted and not all(
            (
                self.repository_boundary_verified,
                self.repository_metadata_safe,
                self.link_safe,
                self.hardlink_safe,
                self.operation_shape_verified,
                self.current_state_verified,
            )
        ):
            raise RollbackRevalidationError(
                "admitted rollback revalidation requires every safety check"
            )


def inspect_repository_rollback_state(
    plan: RepositoryRollbackPlan,
    *,
    repository_root: Union[str, Path],
) -> RepositoryRollbackRevalidationRecord:
    """Observe the exact rollback target without performing or authorizing rollback."""
    if not isinstance(plan, RepositoryRollbackPlan):
        raise TypeError("plan must be RepositoryRollbackPlan")
    if plan.execution_enabled is not False or plan.rollback_executed is not False:
        raise RollbackRevalidationError("rollback plan unexpectedly enables execution")

    requested_path, parts = _canonical_repo_path(plan.requested_path)
    root = Path(repository_root)
    if not root.is_absolute():
        raise RollbackRevalidationError("repository_root must be absolute")

    root_ok = root.exists() and root.is_dir() and (root / ".git").exists()
    if not root_ok:
        return RepositoryRollbackRevalidationRecord(
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            resource_id=plan.resource_id,
            requested_path=requested_path,
            repository_root=str(root),
            resolved_path=None,
            admitted=False,
            reason="rollback revalidation blocked:repository root",
            repository_boundary_verified=False,
            repository_metadata_safe=False,
            link_safe=False,
            hardlink_safe=False,
            operation_shape_verified=False,
            current_state_verified=False,
            observed_target_exists=False,
            observed_content_sha256=None,
        )

    resolved_root = root.resolve(strict=True)
    target = root.joinpath(*parts)
    resolved_target = target.resolve(strict=False)
    boundary_ok = (
        resolved_target != resolved_root
        and resolved_target.is_relative_to(resolved_root)
    )
    metadata_safe = all(part.lower() != ".git" for part in parts)

    candidates = [root]
    cursor = root
    for part in parts[:-1]:
        cursor = cursor / part
        candidates.append(cursor)
    ancestor_link_like = any(_is_link_like(p) for p in candidates if p.exists())
    target_link_like = _is_link_like(target) if target.exists() or target.is_symlink() else False
    link_safe = not ancestor_link_like and not target_link_like

    observed_exists = target.exists()
    hardlink_safe = not _has_multiple_hardlinks(target)
    observed_sha: str | None = None
    if observed_exists and target.is_file() and link_safe:
        observed_sha = _hash_file(target)

    parent = target.parent
    operation_shape_ok = (
        parent.exists()
        and parent.is_dir()
        and not _is_link_like(parent)
        and (not observed_exists or target.is_file())
    )

    current_state_ok = observed_exists is plan.expected_current_target_exists
    if current_state_ok and observed_exists:
        current_state_ok = (
            observed_sha is not None
            and observed_sha == plan.expected_current_content_sha256
        )
    elif current_state_ok and not observed_exists:
        current_state_ok = plan.expected_current_content_sha256 is None

    checks = {
        "repository boundary": boundary_ok,
        "repository metadata": metadata_safe,
        "link safety": link_safe,
        "hardlink safety": hardlink_safe,
        "operation shape": operation_shape_ok,
        "current state": current_state_ok,
    }
    failed = [name for name, passed in checks.items() if not passed]
    admitted = not failed
    reason = (
        "rollback path and current state verified; execution remains disabled"
        if admitted
        else "rollback revalidation blocked:" + ",".join(failed)
    )
    return RepositoryRollbackRevalidationRecord(
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        resource_id=plan.resource_id,
        requested_path=requested_path,
        repository_root=str(resolved_root),
        resolved_path=str(resolved_target),
        admitted=admitted,
        reason=reason,
        repository_boundary_verified=boundary_ok,
        repository_metadata_safe=metadata_safe,
        link_safe=link_safe,
        hardlink_safe=hardlink_safe,
        operation_shape_verified=operation_shape_ok,
        current_state_verified=current_state_ok,
        observed_target_exists=observed_exists,
        observed_content_sha256=observed_sha,
    )
