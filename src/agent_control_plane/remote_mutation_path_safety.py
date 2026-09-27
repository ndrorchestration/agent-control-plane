"""Read-only path-safety admission for candidate repository mutations.

This layer inspects path facts for an already-admitted mutation composition.
It never writes, deletes, renames, creates, or otherwise mutates repository state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Union

from .remote_mutation_composition import MutationCompositionRecord
from .remote_mutation_transaction import MutationPlan

MUTATION_PATH_SAFETY_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-path-safety.v0-candidate"
)

_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


class MutationPathSafetyError(ValueError):
    pass


def _sha256(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise MutationPathSafetyError(f"{field_name} must be lowercase sha256")
    return value


def _canonical_repo_path(value: str) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str) or not value:
        raise MutationPathSafetyError("mutation path must not be blank")
    if "\x00" in value or any(ord(ch) < 32 for ch in value):
        raise MutationPathSafetyError("mutation path contains control characters")
    if "\\" in value:
        raise MutationPathSafetyError("mutation path must use canonical '/' separators")
    if PurePosixPath(value).is_absolute() or value.startswith("/"):
        raise MutationPathSafetyError("mutation path must be repository-relative")
    if len(value) >= 2 and value[1] == ":" and value[0].isalpha():
        raise MutationPathSafetyError("mutation path must not use a drive-qualified path")

    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise MutationPathSafetyError("mutation path contains non-canonical segments")
    if PurePosixPath(value).as_posix() != value:
        raise MutationPathSafetyError("mutation path must be canonical")

    for part in parts:
        if ":" in part:
            raise MutationPathSafetyError("mutation path must not contain ':'")
        if part.startswith(" ") or part.endswith((" ", ".")):
            raise MutationPathSafetyError(
                "mutation path segment must not start/end with space or end with dot"
            )
        basename = part.split(".", 1)[0].lower()
        if basename in _WINDOWS_RESERVED_BASENAMES:
            raise MutationPathSafetyError(
                "mutation path contains a reserved Windows device name"
            )
    return value, parts


@dataclass(frozen=True)
class MutationPathSafetyRecord:
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    requested_path: str
    repository_root: str
    resolved_path: str | None
    admitted: bool
    reason: str
    repository_boundary_verified: bool
    symlink_safe: bool
    repository_metadata_safe: bool
    operation_shape_verified: bool
    target_exists: bool = False
    execution_enabled: bool = False
    mutation_executed: bool = False
    schema_version: str = MUTATION_PATH_SAFETY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _sha256(self.plan_sha256, "plan_sha256")
        if self.execution_enabled is not False or self.mutation_executed is not False:
            raise MutationPathSafetyError(
                "path-safety record cannot enable or claim mutation execution"
            )
        if self.admitted and not all(
            (
                self.repository_boundary_verified,
                self.symlink_safe,
                self.repository_metadata_safe,
                self.operation_shape_verified,
            )
        ):
            raise MutationPathSafetyError(
                "admitted path safety requires all safety checks"
            )


def _record(
    *,
    composition: MutationCompositionRecord,
    plan: MutationPlan,
    requested_path: str,
    repository_root: Path,
    resolved_path: Path | None,
    admitted: bool,
    reason: str,
    repository_boundary_verified: bool,
    symlink_safe: bool,
    repository_metadata_safe: bool,
    operation_shape_verified: bool,
    target_exists: bool,
) -> MutationPathSafetyRecord:
    return MutationPathSafetyRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=requested_path,
        repository_root=str(repository_root),
        resolved_path=str(resolved_path) if resolved_path is not None else None,
        admitted=admitted,
        reason=reason,
        repository_boundary_verified=repository_boundary_verified,
        symlink_safe=symlink_safe,
        repository_metadata_safe=repository_metadata_safe,
        operation_shape_verified=operation_shape_verified,
        target_exists=target_exists,
    )


def inspect_repository_mutation_path(
    composition: MutationCompositionRecord,
    plan: MutationPlan,
    *,
    repository_root: Union[str, Path],
) -> MutationPathSafetyRecord:
    """Inspect one planned repository path without enabling mutation execution."""
    if not isinstance(composition, MutationCompositionRecord):
        raise TypeError("composition must be MutationCompositionRecord")
    if not isinstance(plan, MutationPlan):
        raise TypeError("plan must be MutationPlan")

    raw_path = plan.parameters.get("path")
    requested_path, parts = _canonical_repo_path(raw_path)

    root = Path(repository_root)
    if not root.is_absolute():
        raise MutationPathSafetyError("repository_root must be absolute")

    composition_matches = (
        composition.admitted is True
        and composition.request_id == plan.request_id
        and composition.resource_id == plan.resource_id
        and composition.operation_id == plan.operation_id
        and composition.plan_sha256 == plan.plan_sha256
        and composition.execution_enabled is False
        and composition.mutation_executed is False
    )
    if not composition_matches:
        return _record(
            composition=composition,
            plan=plan,
            requested_path=requested_path,
            repository_root=root,
            resolved_path=None,
            admitted=False,
            reason="admitted composition does not match exact mutation plan",
            repository_boundary_verified=False,
            symlink_safe=False,
            repository_metadata_safe=False,
            operation_shape_verified=False,
            target_exists=False,
        )

    if not root.exists() or not root.is_dir():
        return _record(
            composition=composition,
            plan=plan,
            requested_path=requested_path,
            repository_root=root,
            resolved_path=None,
            admitted=False,
            reason="repository root is not an existing directory",
            repository_boundary_verified=False,
            symlink_safe=False,
            repository_metadata_safe=False,
            operation_shape_verified=False,
            target_exists=False,
        )

    git_marker = root / ".git"
    if not git_marker.exists():
        return _record(
            composition=composition,
            plan=plan,
            requested_path=requested_path,
            repository_root=root,
            resolved_path=None,
            admitted=False,
            reason="repository root lacks .git marker",
            repository_boundary_verified=False,
            symlink_safe=False,
            repository_metadata_safe=False,
            operation_shape_verified=False,
            target_exists=False,
        )

    metadata_safe = all(part.lower() != ".git" for part in parts)
    target = root.joinpath(*parts)
    resolved_root = root.resolve(strict=True)
    resolved_target = target.resolve(strict=False)
    boundary_verified = (
        resolved_target != resolved_root
        and resolved_target.is_relative_to(resolved_root)
    )

    candidates = [root]
    cursor = root
    for part in parts[:-1]:
        cursor = cursor / part
        candidates.append(cursor)
    ancestor_symlink = any(path.is_symlink() for path in candidates if path.exists())
    target_symlink = target.is_symlink()
    target_exists = target.exists()
    symlink_safe = not ancestor_symlink and not target_symlink

    if plan.operation_id == "repo.write_text_file":
        parent = target.parent
        operation_shape_verified = (
            parent.exists()
            and parent.is_dir()
            and (not target.exists() or target.is_file())
        )
    elif plan.operation_id == "repo.delete_file":
        operation_shape_verified = target.exists() and target.is_file()
    else:
        operation_shape_verified = False

    checks = {
        "repository boundary": boundary_verified,
        "symlink safety": symlink_safe,
        "repository metadata": metadata_safe,
        "operation shape": operation_shape_verified,
    }
    failed = [name for name, passed in checks.items() if not passed]
    admitted = not failed
    reason = (
        "repository path safety verified; execution remains disabled"
        if admitted
        else "path safety blocked:" + ",".join(failed)
    )

    return _record(
        composition=composition,
        plan=plan,
        requested_path=requested_path,
        repository_root=root,
        resolved_path=resolved_target,
        admitted=admitted,
        reason=reason,
        repository_boundary_verified=boundary_verified,
        symlink_safe=symlink_safe,
        repository_metadata_safe=metadata_safe,
        operation_shape_verified=operation_shape_verified,
        target_exists=target_exists,
    )
