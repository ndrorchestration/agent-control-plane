"""Bounded experimental repository rollback executor candidate.

This is the first rollback tranche capable of changing repository file state.
It is disabled by default, accepts only explicitly allowlisted repository roots,
supports only the two existing rollback actions, and is intended for disposable
synthetic repositories until separately authorized.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .remote_mutation_rollback_authorization import (
    RepositoryRollbackAuthorization,
    RepositoryRollbackAuthorizationStore,
)
from .remote_mutation_rollback_journal import (
    RemoteMutationRollbackJournal,
    RollbackJournalState,
)
from .remote_mutation_rollback_material_readback import (
    RollbackMaterialReadbackRecord,
)
from .remote_mutation_rollback_plan import (
    RepositoryRollbackPlan,
    RollbackAction,
)
from .remote_mutation_rollback_revalidation import (
    RepositoryRollbackRevalidationRecord,
    inspect_repository_rollback_state,
)

ROLLBACK_EXECUTOR_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-executor.v0-candidate"
)
DEFAULT_ROLLBACK_EXECUTOR_ID = "acp:repository-rollback-executor:v0-candidate"


class RepositoryRollbackExecutorError(ValueError):
    pass


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RepositoryRollbackExecutionResult:
    authorization_id: str
    rollback_transaction_id: str
    rollback_plan_sha256: str
    rollback_executor_id: str
    requested_path: str
    action: RollbackAction
    authorization_consumed: bool
    rollback_intent_recorded: bool
    rollback_effect_reported: bool
    rollback_postcondition_verified: bool
    final_target_exists: bool
    final_content_sha256: str | None
    rollback_effect_sha256: str
    rollback_verification_sha256: str
    rollback_executed: bool
    schema_version: str = ROLLBACK_EXECUTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.rollback_executed is not True:
            raise RepositoryRollbackExecutorError(
                "successful rollback execution result must record rollback_executed=true"
            )


class AuthorizedRepositoryRollbackExecutor:
    """Explicitly enabled, root-allowlisted rollback executor."""

    def __init__(
        self,
        *,
        allowed_repository_roots: Iterable[str | Path],
        experimental_enable: bool = False,
        rollback_executor_id: str = DEFAULT_ROLLBACK_EXECUTOR_ID,
    ) -> None:
        if experimental_enable is not True:
            raise RepositoryRollbackExecutorError(
                "rollback executor requires explicit experimental_enable=True"
            )
        roots = tuple(Path(root).resolve(strict=True) for root in allowed_repository_roots)
        if not roots:
            raise RepositoryRollbackExecutorError(
                "rollback executor requires at least one allowlisted repository root"
            )
        for root in roots:
            if not root.is_dir() or not (root / ".git").exists():
                raise RepositoryRollbackExecutorError(
                    "allowlisted rollback root must be an existing repository"
                )
        if not isinstance(rollback_executor_id, str) or not rollback_executor_id.strip():
            raise RepositoryRollbackExecutorError("rollback_executor_id must not be blank")
        self.allowed_repository_roots = frozenset(roots)
        self.rollback_executor_id = rollback_executor_id.strip()

    def _allowed_root(self, repository_root: str | Path) -> Path:
        root = Path(repository_root).resolve(strict=True)
        if root not in self.allowed_repository_roots:
            raise RepositoryRollbackExecutorError(
                "repository root is not in rollback executor allowlist"
            )
        if not root.is_dir() or not (root / ".git").exists():
            raise RepositoryRollbackExecutorError(
                "allowlisted repository root no longer satisfies repository boundary"
            )
        return root

    @staticmethod
    def _validate_material(
        plan: RepositoryRollbackPlan,
        readback: RollbackMaterialReadbackRecord,
        rollback_material: bytes | None,
    ) -> None:
        if readback.admitted is not True:
            raise RepositoryRollbackExecutorError(
                "rollback material readback must be admitted"
            )
        if (
            readback.rollback_transaction_id != plan.rollback_transaction_id
            or readback.rollback_plan_sha256 != plan.rollback_plan_sha256
            or readback.rollback_descriptor_sha256
            != plan.rollback_descriptor_sha256
            or readback.rollback_custody_ref != plan.rollback_custody_ref
        ):
            raise RepositoryRollbackExecutorError(
                "rollback material readback identity mismatch"
            )
        if readback.authorization_consumed:
            raise RepositoryRollbackExecutorError(
                "rollback material readback was taken after authorization consumption"
            )

        if plan.action is RollbackAction.RESTORE_FILE_BYTES:
            if not isinstance(rollback_material, bytes):
                raise RepositoryRollbackExecutorError(
                    "restore rollback requires bytes material"
                )
            if (
                readback.observed_material_sha256 != _hash_bytes(rollback_material)
                or readback.observed_material_size != len(rollback_material)
                or plan.desired_content_sha256 != _hash_bytes(rollback_material)
            ):
                raise RepositoryRollbackExecutorError(
                    "rollback material bytes do not match verified readback/plan"
                )
        elif plan.action is RollbackAction.DELETE_CREATED_FILE:
            if rollback_material is not None:
                raise RepositoryRollbackExecutorError(
                    "delete-created rollback must not receive material bytes"
                )
        else:
            raise RepositoryRollbackExecutorError("unsupported rollback action")

    @staticmethod
    def _atomic_write(target: Path, content: bytes) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=".acp-rollback-",
            suffix=".tmp",
            dir=str(target.parent),
        )
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()

    @staticmethod
    def _perform_rollback(
        plan: RepositoryRollbackPlan,
        target: Path,
        *,
        rollback_material: bytes | None,
    ) -> None:
        if plan.action is RollbackAction.RESTORE_FILE_BYTES:
            assert isinstance(rollback_material, bytes)
            AuthorizedRepositoryRollbackExecutor._atomic_write(
                target, rollback_material
            )
            return
        if plan.action is RollbackAction.DELETE_CREATED_FILE:
            target.unlink()
            return
        raise RepositoryRollbackExecutorError("unsupported rollback action")

    @staticmethod
    def _verify_postcondition(
        plan: RepositoryRollbackPlan,
        target: Path,
    ) -> tuple[bool, bool, str | None]:
        exists = target.exists()
        observed = (
            _hash_file(target)
            if exists and target.is_file() and not target.is_symlink()
            else None
        )
        verified = (
            exists is plan.desired_target_exists
            and observed == plan.desired_content_sha256
        )
        return verified, exists, observed

    def execute(
        self,
        *,
        authorization_store: RepositoryRollbackAuthorizationStore,
        authorization_id: str,
        journal_store: RemoteMutationRollbackJournal,
        plan: RepositoryRollbackPlan,
        prior_revalidation: RepositoryRollbackRevalidationRecord,
        material_readback: RollbackMaterialReadbackRecord,
        repository_root: str | Path,
        rollback_material: bytes | None,
        authorization_consumed_at: str,
        rollback_intent_at: str,
        rollback_effect_at: str,
        rollback_verified_at: str,
    ) -> RepositoryRollbackExecutionResult:
        root = self._allowed_root(repository_root)

        durable_auth = authorization_store.get(authorization_id)
        if durable_auth is None:
            raise RepositoryRollbackExecutorError(
                "rollback authorization not found"
            )
        if durable_auth.consumed:
            raise RepositoryRollbackExecutorError(
                "rollback authorization already consumed"
            )
        if durable_auth.rollback_executor_id != self.rollback_executor_id:
            raise RepositoryRollbackExecutorError(
                "rollback executor identity does not match authorization"
            )
        if (
            durable_auth.rollback_transaction_id != plan.rollback_transaction_id
            or durable_auth.rollback_plan_sha256 != plan.rollback_plan_sha256
            or durable_auth.rollback_descriptor_sha256
            != plan.rollback_descriptor_sha256
            or durable_auth.rollback_custody_ref != plan.rollback_custody_ref
        ):
            raise RepositoryRollbackExecutorError(
                "rollback authorization identity mismatch"
            )

        journal_before = journal_store.get(plan.rollback_transaction_id)
        if journal_before is None:
            raise RepositoryRollbackExecutorError(
                "rollback journal transaction not found"
            )
        if journal_before.current_state is not RollbackJournalState.PREPARED:
            raise RepositoryRollbackExecutorError(
                "rollback journal must be PREPARED before executor start"
            )
        if journal_before.rollback_plan_sha256 != plan.rollback_plan_sha256:
            raise RepositoryRollbackExecutorError(
                "rollback journal plan identity mismatch"
            )

        current = inspect_repository_rollback_state(
            plan, repository_root=root
        )
        if current.admitted is not True:
            raise RepositoryRollbackExecutorError(
                "rollback current-state revalidation failed before authorization consumption"
            )
        if (
            prior_revalidation.rollback_plan_sha256 != current.rollback_plan_sha256
            or prior_revalidation.requested_path != current.requested_path
            or prior_revalidation.observed_target_exists
            != current.observed_target_exists
            or prior_revalidation.observed_content_sha256
            != current.observed_content_sha256
        ):
            raise RepositoryRollbackExecutorError(
                "rollback state changed since admitted revalidation"
            )

        self._validate_material(plan, material_readback, rollback_material)

        consumed: RepositoryRollbackAuthorization = authorization_store.consume(
            authorization_id,
            rollback_executor_id=self.rollback_executor_id,
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            now=authorization_consumed_at,
        )
        journal_store.append(
            plan.rollback_transaction_id,
            state=RollbackJournalState.ROLLBACK_INTENT_RECORDED,
            occurred_at=rollback_intent_at,
        )

        target = root.joinpath(*plan.requested_path.split("/"))
        try:
            second = inspect_repository_rollback_state(
                plan, repository_root=root
            )
            if second.admitted is not True:
                raise RepositoryRollbackExecutorError(
                    "rollback revalidation failed immediately before side effect"
                )
            if (
                second.resolved_path != current.resolved_path
                or second.observed_target_exists != current.observed_target_exists
                or second.observed_content_sha256 != current.observed_content_sha256
            ):
                raise RepositoryRollbackExecutorError(
                    "rollback target changed immediately before side effect"
                )

            self._perform_rollback(
                plan,
                target,
                rollback_material=rollback_material,
            )

            exists_after = target.exists()
            sha_after = (
                _hash_file(target)
                if exists_after and target.is_file() and not target.is_symlink()
                else None
            )
            effect_sha = _evidence_hash(
                self.rollback_executor_id,
                plan.rollback_transaction_id,
                plan.rollback_plan_sha256,
                plan.requested_path,
                str(exists_after),
                sha_after or "absent",
            )
            journal_store.append(
                plan.rollback_transaction_id,
                state=RollbackJournalState.ROLLBACK_EFFECT_REPORTED,
                occurred_at=rollback_effect_at,
                evidence_sha256=effect_sha,
            )

            verified, final_exists, final_sha = self._verify_postcondition(
                plan, target
            )
            if not verified:
                journal_store.append(
                    plan.rollback_transaction_id,
                    state=RollbackJournalState.FAILED,
                    occurred_at=rollback_verified_at,
                    error="rollback postcondition verification failed",
                )
                raise RepositoryRollbackExecutorError(
                    "rollback postcondition verification failed"
                )

            verification_sha = _evidence_hash(
                effect_sha,
                str(final_exists),
                final_sha or "absent",
                plan.desired_content_sha256 or "absent",
            )
            journal_store.append(
                plan.rollback_transaction_id,
                state=RollbackJournalState.ROLLBACK_VERIFIED,
                occurred_at=rollback_verified_at,
                evidence_sha256=verification_sha,
            )
            return RepositoryRollbackExecutionResult(
                authorization_id=consumed.authorization_id,
                rollback_transaction_id=plan.rollback_transaction_id,
                rollback_plan_sha256=plan.rollback_plan_sha256,
                rollback_executor_id=self.rollback_executor_id,
                requested_path=plan.requested_path,
                action=plan.action,
                authorization_consumed=consumed.consumed,
                rollback_intent_recorded=True,
                rollback_effect_reported=True,
                rollback_postcondition_verified=True,
                final_target_exists=final_exists,
                final_content_sha256=final_sha,
                rollback_effect_sha256=effect_sha,
                rollback_verification_sha256=verification_sha,
                rollback_executed=True,
            )
        except Exception as exc:
            latest = journal_store.get(plan.rollback_transaction_id)
            if (
                latest is not None
                and latest.current_state
                not in {RollbackJournalState.ROLLBACK_VERIFIED, RollbackJournalState.FAILED}
            ):
                try:
                    journal_store.append(
                        plan.rollback_transaction_id,
                        state=RollbackJournalState.FAILED,
                        occurred_at=rollback_verified_at,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:
                    pass
            if isinstance(exc, RepositoryRollbackExecutorError):
                raise
            raise RepositoryRollbackExecutorError(
                f"rollback executor failed: {type(exc).__name__}: {exc}"
            ) from exc
