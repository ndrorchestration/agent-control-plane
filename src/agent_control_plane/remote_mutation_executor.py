"""Experimental bounded repository mutation executor candidate.

This is the first ACP tranche that can perform repository file side effects.
It is disabled unless explicitly constructed with experimental_enable=True and
an exact repository-root allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .remote_mutation_composition import MutationCompositionRecord
from .remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorization,
    RemoteMutationExecutionAuthorizationStore,
)
from .remote_mutation_execution_closure import (
    MutationExecutionClosureRecord,
    close_authorized_mutation_execution,
)
from .remote_mutation_execution_evidence import (
    ExternalMutationExecutionEvidence,
    MutationExecutionEvidenceReceipt,
    bind_mutation_execution_evidence,
)
from .remote_mutation_journal import (
    MutationJournalState,
    RemoteMutationJournal,
)
from .remote_mutation_path_safety import (
    MutationPathSafetyRecord,
    inspect_repository_mutation_path,
)
from .remote_mutation_postcondition import (
    MutationPostconditionRecord,
    verify_repository_mutation_postcondition,
)
from .remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from .remote_mutation_transaction import MutationPlan


REPOSITORY_MUTATION_EXECUTOR_SCHEMA_VERSION = (
    "agent-control-plane.repository-mutation-executor.v0-candidate"
)
DEFAULT_REPOSITORY_MUTATION_EXECUTOR_ID = (
    "acp.repository-mutation-executor.v0-candidate"
)


class RepositoryMutationExecutorError(RuntimeError):
    pass


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: dict[str, object]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _postcondition_evidence_sha256(record: MutationPostconditionRecord) -> str:
    return _canonical_sha256(
        {
            "operation_id": record.operation_id,
            "plan_sha256": record.plan_sha256,
            "postcondition_verified": record.postcondition_verified,
            "request_id": record.request_id,
            "requested_path": record.requested_path,
            "resource_id": record.resource_id,
            "target_exists": record.target_exists,
            "observed_content_sha256": record.observed_content_sha256,
            "path_revalidated": record.path_revalidated,
        }
    )


@dataclass(frozen=True)
class RepositoryMutationExecutionResult:
    execution_id: str
    executor_id: str
    transaction_id: str
    operation_id: str
    plan_sha256: str
    path: str
    target_exists_after: bool
    content_sha256_after: str | None
    external_effect_sha256: str
    postcondition_evidence_sha256: str
    result_sha256: str
    authorization: RemoteMutationExecutionAuthorization
    postcondition: MutationPostconditionRecord
    evidence_receipt: MutationExecutionEvidenceReceipt
    closure: MutationExecutionClosureRecord
    schema_version: str = REPOSITORY_MUTATION_EXECUTOR_SCHEMA_VERSION


class AuthorizedRepositoryMutationExecutor:
    """Exact-root allowlisted repository file mutator.

    The executor intentionally supports only the operation registry's current
    repository file operations. It has no shell/argv execution surface.
    """

    def __init__(
        self,
        *,
        executor_id: str = DEFAULT_REPOSITORY_MUTATION_EXECUTOR_ID,
        allowed_repository_roots: Iterable[str | Path],
        experimental_enable: bool = False,
    ) -> None:
        if experimental_enable is not True:
            raise RepositoryMutationExecutorError(
                "live repository mutation executor requires explicit experimental_enable=True"
            )
        if not isinstance(executor_id, str) or not executor_id.strip():
            raise RepositoryMutationExecutorError("executor_id must not be blank")
        roots: list[Path] = []
        for root in allowed_repository_roots:
            path = Path(root)
            if not path.is_absolute():
                raise RepositoryMutationExecutorError(
                    "allowed repository roots must be absolute"
                )
            roots.append(path.resolve(strict=True))
        if not roots:
            raise RepositoryMutationExecutorError(
                "at least one allowed repository root is required"
            )
        self.executor_id = executor_id.strip()
        self.allowed_repository_roots = tuple(dict.fromkeys(roots))

    def _allowed_root(self, repository_root: str | Path) -> Path:
        root = Path(repository_root)
        if not root.is_absolute():
            raise RepositoryMutationExecutorError("repository_root must be absolute")
        resolved = root.resolve(strict=True)
        if resolved not in self.allowed_repository_roots:
            raise RepositoryMutationExecutorError(
                "repository_root is not in executor allowlist"
            )
        if not (resolved / ".git").exists():
            raise RepositoryMutationExecutorError(
                "repository_root lacks .git marker"
            )
        return resolved

    @staticmethod
    def _verify_rollback_precondition(
        plan: MutationPlan,
        descriptor: RollbackMaterialDescriptor,
        target: Path,
    ) -> None:
        if descriptor.operation_id != plan.operation_id:
            raise RepositoryMutationExecutorError(
                "rollback descriptor operation does not match plan"
            )
        if descriptor.path != plan.parameters["path"]:
            raise RepositoryMutationExecutorError(
                "rollback descriptor path does not match plan"
            )
        if descriptor.descriptor_sha256 != plan.rollback_sha256:
            raise RepositoryMutationExecutorError(
                "rollback descriptor identity does not match plan"
            )

        if plan.operation_id == "repo.write_text_file":
            if descriptor.mode is RollbackMode.RESTORE_FILE_BYTES:
                if not target.exists() or not target.is_file() or target.is_symlink():
                    raise RepositoryMutationExecutorError(
                        "existing-file rollback precondition no longer holds"
                    )
                if _hash_file(target) != descriptor.prior_content_sha256:
                    raise RepositoryMutationExecutorError(
                        "existing-file content drifted after authorization"
                    )
            elif descriptor.mode is RollbackMode.DELETE_CREATED_FILE:
                if target.exists() or target.is_symlink():
                    raise RepositoryMutationExecutorError(
                        "new-file rollback precondition no longer holds"
                    )
            else:
                raise RepositoryMutationExecutorError(
                    "unsupported write rollback mode"
                )
        elif plan.operation_id == "repo.delete_file":
            if descriptor.mode is not RollbackMode.RESTORE_FILE_BYTES:
                raise RepositoryMutationExecutorError(
                    "delete requires restore-file rollback material"
                )
            if not target.exists() or not target.is_file() or target.is_symlink():
                raise RepositoryMutationExecutorError(
                    "delete target precondition no longer holds"
                )
            current = _hash_file(target)
            if (
                current != descriptor.prior_content_sha256
                or current != plan.parameters["prior_content_sha256"]
            ):
                raise RepositoryMutationExecutorError(
                    "delete target content drifted after authorization"
                )
        else:
            raise RepositoryMutationExecutorError(
                "unsupported repository mutation operation"
            )

    @staticmethod
    def _write_atomic(target: Path, content: bytes) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=".acp-mutation-",
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
    def _validate_operation_input(
        plan: MutationPlan,
        *,
        content: bytes | None,
    ) -> None:
        if plan.operation_id == "repo.write_text_file":
            if not isinstance(content, bytes):
                raise RepositoryMutationExecutorError(
                    "write operation requires bytes content"
                )
            if _hash_bytes(content) != plan.parameters["content_sha256"]:
                raise RepositoryMutationExecutorError(
                    "write content sha256 does not match exact plan"
                )
            return
        if plan.operation_id == "repo.delete_file":
            if content is not None:
                raise RepositoryMutationExecutorError(
                    "delete operation must not receive content"
                )
            return
        raise RepositoryMutationExecutorError(
            "unsupported repository mutation operation"
        )

    @staticmethod
    def _perform_side_effect(
        plan: MutationPlan,
        target: Path,
        *,
        content: bytes | None,
    ) -> None:
        AuthorizedRepositoryMutationExecutor._validate_operation_input(
            plan,
            content=content,
        )
        if plan.operation_id == "repo.write_text_file":
            assert isinstance(content, bytes)
            AuthorizedRepositoryMutationExecutor._write_atomic(target, content)
            return
        if plan.operation_id == "repo.delete_file":
            target.unlink()
            return
        raise RepositoryMutationExecutorError(
            "unsupported repository mutation operation"
        )

    def execute(
        self,
        *,
        authorization_store: RemoteMutationExecutionAuthorizationStore,
        authorization_id: str,
        journal_store: RemoteMutationJournal,
        composition: MutationCompositionRecord,
        plan: MutationPlan,
        prior_path_safety: MutationPathSafetyRecord,
        rollback_custody: RollbackCustodyAdmissionRecord,
        rollback_descriptor: RollbackMaterialDescriptor,
        repository_root: str | Path,
        execution_id: str,
        content: bytes | None,
        authorization_consumed_at: str,
        execution_intent_at: str,
        external_effect_at: str,
        postcondition_at: str,
    ) -> RepositoryMutationExecutionResult:
        root = self._allowed_root(repository_root)
        pending_authorization = authorization_store.get(authorization_id)
        if pending_authorization is None:
            raise RepositoryMutationExecutorError(
                "mutation execution authorization not found"
            )
        journal_before = journal_store.get(pending_authorization.transaction_id)
        if journal_before is None:
            raise RepositoryMutationExecutorError(
                "authorization journal transaction not found"
            )
        if journal_before.current_state is not MutationJournalState.PREPARED:
            raise RepositoryMutationExecutorError(
                "journal must be PREPARED before executor start"
            )

        current_safety = inspect_repository_mutation_path(
            composition,
            plan,
            repository_root=root,
        )
        if current_safety.admitted is not True:
            raise RepositoryMutationExecutorError(
                "repository path safety revalidation failed before authorization consumption"
            )
        if (
            prior_path_safety.plan_sha256 != current_safety.plan_sha256
            or prior_path_safety.requested_path != current_safety.requested_path
            or rollback_custody.plan_sha256 != plan.plan_sha256
            or rollback_custody.descriptor_sha256 != plan.rollback_sha256
            or rollback_custody.admitted is not True
            or rollback_custody.readback_verified is not True
        ):
            raise RepositoryMutationExecutorError(
                "pre-execution safety/custody identity mismatch"
            )

        target = root.joinpath(*plan.parameters["path"].split("/"))
        self._verify_rollback_precondition(plan, rollback_descriptor, target)
        self._validate_operation_input(plan, content=content)

        authorization = authorization_store.consume(
            authorization_id,
            executor_id=self.executor_id,
            transaction_id=journal_before.transaction_id,
            plan_sha256=plan.plan_sha256,
            now=authorization_consumed_at,
        )

        journal_store.append(
            journal_before.transaction_id,
            state=MutationJournalState.EXECUTION_INTENT_RECORDED,
            occurred_at=execution_intent_at,
        )

        try:
            second_safety = inspect_repository_mutation_path(
                composition,
                plan,
                repository_root=root,
            )
            if second_safety.admitted is not True:
                raise RepositoryMutationExecutorError(
                    "repository path safety revalidation failed immediately before side effect"
                )
            self._verify_rollback_precondition(plan, rollback_descriptor, target)
            self._perform_side_effect(plan, target, content=content)

            effect_payload = {
                "execution_id": execution_id,
                "operation_id": plan.operation_id,
                "path": plan.parameters["path"],
                "plan_sha256": plan.plan_sha256,
                "target_exists": target.exists(),
                "content_sha256": (
                    _hash_file(target)
                    if target.exists() and target.is_file() and not target.is_symlink()
                    else None
                ),
            }
            effect_sha = _canonical_sha256(effect_payload)
            journal_store.append(
                journal_before.transaction_id,
                state=MutationJournalState.EXTERNAL_EFFECT_REPORTED,
                occurred_at=external_effect_at,
                evidence_sha256=effect_sha,
            )

            postcondition = verify_repository_mutation_postcondition(
                plan,
                prior_path_safety,
                rollback_custody,
                repository_root=root,
            )
            if postcondition.postcondition_verified is not True:
                journal_store.append(
                    journal_before.transaction_id,
                    state=MutationJournalState.FAILED,
                    occurred_at=postcondition_at,
                    error=postcondition.reason,
                )
                raise RepositoryMutationExecutorError(
                    "repository mutation postcondition verification failed"
                )

            post_sha = _postcondition_evidence_sha256(postcondition)
            journal_store.append(
                journal_before.transaction_id,
                state=MutationJournalState.POSTCONDITION_VERIFIED,
                occurred_at=postcondition_at,
                evidence_sha256=post_sha,
            )
            journal_after = journal_store.get(journal_before.transaction_id)
            assert journal_after is not None

            result_payload = {
                "execution_id": execution_id,
                "executor_id": self.executor_id,
                "external_effect_sha256": effect_sha,
                "plan_sha256": plan.plan_sha256,
                "postcondition_evidence_sha256": post_sha,
                "transaction_id": journal_before.transaction_id,
            }
            result_sha = _canonical_sha256(result_payload)
            evidence = ExternalMutationExecutionEvidence(
                executor_id=self.executor_id,
                execution_id=execution_id,
                transaction_id=journal_before.transaction_id,
                request_id=plan.request_id,
                resource_id=plan.resource_id,
                operation_id=plan.operation_id,
                plan_sha256=plan.plan_sha256,
                result_sha256=result_sha,
                external_effect_sha256=effect_sha,
                postcondition_evidence_sha256=post_sha,
            )
            evidence_receipt = bind_mutation_execution_evidence(
                plan,
                journal_after,
                postcondition,
                evidence,
            )
            if evidence_receipt.evidence_bound is not True:
                raise RepositoryMutationExecutorError(
                    "execution evidence failed to bind"
                )
            closure = close_authorized_mutation_execution(
                authorization,
                journal_after,
                evidence_receipt,
            )
            if closure.closed is not True:
                raise RepositoryMutationExecutorError(
                    "authorized execution failed terminal closure"
                )

            return RepositoryMutationExecutionResult(
                execution_id=execution_id,
                executor_id=self.executor_id,
                transaction_id=journal_before.transaction_id,
                operation_id=plan.operation_id,
                plan_sha256=plan.plan_sha256,
                path=plan.parameters["path"],
                target_exists_after=postcondition.target_exists,
                content_sha256_after=postcondition.observed_content_sha256,
                external_effect_sha256=effect_sha,
                postcondition_evidence_sha256=post_sha,
                result_sha256=result_sha,
                authorization=authorization,
                postcondition=postcondition,
                evidence_receipt=evidence_receipt,
                closure=closure,
            )
        except Exception as exc:
            latest = journal_store.get(journal_before.transaction_id)
            if (
                latest is not None
                and latest.current_state
                not in {
                    MutationJournalState.POSTCONDITION_VERIFIED,
                    MutationJournalState.ROLLBACK_VERIFIED,
                    MutationJournalState.FAILED,
                }
            ):
                try:
                    journal_store.append(
                        journal_before.transaction_id,
                        state=MutationJournalState.FAILED,
                        occurred_at=postcondition_at,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:
                    pass
            if isinstance(exc, RepositoryMutationExecutorError):
                raise
            raise RepositoryMutationExecutorError(
                f"repository mutation executor failed: {type(exc).__name__}: {exc}"
            ) from exc
