"""Authorized transactional orchestration for future Windows SCM installation.

The executor is backend-injected. This module does not itself call Windows SCM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, runtime_checkable

from .authority import AuthorityValidationError
from .windows_scm_install_authorization import (
    WindowsScmInstallationAuthorizationStore,
    WindowsScmInstallationTarget,
    windows_scm_registration_plan_sha256,
)
from .windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)
from .windows_scm_install_journal import (
    WindowsScmInstallationJournal,
    WindowsScmInstallJournalState,
)


@runtime_checkable
class WindowsScmInstallationBackend(Protocol):
    def open_scm(self, desired_access: int): ...
    def create_service(
        self,
        scm_handle,
        plan: WindowsScmServiceRegistrationPlan,
        credential_secret: Optional[str],
    ): ...
    def configure_delayed_auto_start(
        self,
        service_handle,
        enabled: bool,
    ) -> None: ...
    def delete_service(self, service_handle) -> None: ...
    def close_handle(self, handle) -> None: ...


@dataclass(frozen=True)
class WindowsScmInstallTransactionResult:
    authorization_id: str
    service_name: str
    manifest_sha256: str
    binary_sha256: str
    registration_plan_sha256: str
    authorization_consumed_at: str
    mutation_steps: tuple[str, ...]
    rollback_performed: bool
    rollback_error: Optional[str] = None


class WindowsScmInstallationTransactionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        mutation_steps: tuple[str, ...],
        rollback_performed: bool,
        rollback_error: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.mutation_steps = mutation_steps
        self.rollback_performed = rollback_performed
        self.rollback_error = rollback_error


class WindowsScmServiceInstallationTransaction:
    """Execute one authorized install against an injected mutation backend."""

    def __init__(
        self,
        *,
        authorization_store: WindowsScmInstallationAuthorizationStore,
        backend: WindowsScmInstallationBackend,
        credential_resolver: Optional[Callable[[str], str]] = None,
        journal: Optional[WindowsScmInstallationJournal] = None,
    ) -> None:
        if not isinstance(
            authorization_store,
            WindowsScmInstallationAuthorizationStore,
        ):
            raise AuthorityValidationError(
                "authorization_store must be "
                "WindowsScmInstallationAuthorizationStore"
            )
        if not isinstance(backend, WindowsScmInstallationBackend):
            raise AuthorityValidationError(
                "backend must implement WindowsScmInstallationBackend"
            )
        if (
            credential_resolver is not None
            and not callable(credential_resolver)
        ):
            raise AuthorityValidationError(
                "credential_resolver must be callable or None"
            )
        if journal is not None and not isinstance(
            journal,
            WindowsScmInstallationJournal,
        ):
            raise AuthorityValidationError(
                "journal must be WindowsScmInstallationJournal or None"
            )
        self.authorization_store = authorization_store
        self.backend = backend
        self.credential_resolver = credential_resolver
        self.journal = journal

    def _validate_exact_target(
        self,
        *,
        target: WindowsScmInstallationTarget,
        plan: WindowsScmServiceRegistrationPlan,
    ) -> None:
        if not isinstance(target, WindowsScmInstallationTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmInstallationTarget"
            )
        if not isinstance(plan, WindowsScmServiceRegistrationPlan):
            raise AuthorityValidationError(
                "plan must be WindowsScmServiceRegistrationPlan"
            )
        if plan.service_name != target.service_name:
            raise AuthorityValidationError(
                "installation plan service name does not match target"
            )
        if plan.manifest_sha256 != target.manifest_sha256:
            raise AuthorityValidationError(
                "installation plan manifest does not match target"
            )
        if (
            windows_scm_registration_plan_sha256(plan)
            != target.registration_plan_sha256
        ):
            raise AuthorityValidationError(
                "installation plan identity does not match target"
            )
        if plan.requires_credential_resolution:
            if plan.credential_reference is None:
                raise AuthorityValidationError(
                    "credential reference required by installation plan"
                )
            if self.credential_resolver is None:
                raise AuthorityValidationError(
                    "credential resolver required by installation plan"
                )

    def install(
        self,
        *,
        authorization_id: str,
        target: WindowsScmInstallationTarget,
        plan: WindowsScmServiceRegistrationPlan,
        now: str,
        transaction_id: Optional[str] = None,
    ) -> WindowsScmInstallTransactionResult:
        self._validate_exact_target(target=target, plan=plan)
        journal_id = transaction_id or authorization_id

        if self.journal is not None:
            self.journal.begin(
                transaction_id=journal_id,
                authorization_id=authorization_id,
                target=target,
                created_at=now,
            )

        # Exact single-use authorization is consumed before any backend call.
        consumed = self.authorization_store.consume(
            authorization_id,
            target=target,
            now=now,
        )
        if self.journal is not None:
            self.journal.append(
                journal_id,
                state=WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
                occurred_at=now,
            )

        credential_secret: Optional[str] = None
        if plan.requires_credential_resolution:
            assert plan.credential_reference is not None
            assert self.credential_resolver is not None
            credential_secret = self.credential_resolver(
                plan.credential_reference
            )
            if (
                not isinstance(credential_secret, str)
                or not credential_secret
            ):
                raise AuthorityValidationError(
                    "credential resolver returned no secret"
                )

        steps: list[str] = ["authorization_consumed"]
        scm_handle = None
        service_handle = None
        rollback_performed = False
        rollback_error: Optional[str] = None

        try:
            scm_handle = self.backend.open_scm(
                plan.desired_scm_access
            )
            steps.append("scm_opened")
            if self.journal is not None:
                self.journal.append(
                    journal_id,
                    state=WindowsScmInstallJournalState.SCM_OPENED,
                    occurred_at=now,
                )
                self.journal.append(
                    journal_id,
                    state=(
                        WindowsScmInstallJournalState.CREATE_INTENT_RECORDED
                    ),
                    occurred_at=now,
                )

            service_handle = self.backend.create_service(
                scm_handle,
                plan,
                credential_secret,
            )
            steps.append("service_created")
            if self.journal is not None:
                self.journal.append(
                    journal_id,
                    state=WindowsScmInstallJournalState.SERVICE_CREATED,
                    occurred_at=now,
                )

            # Drop the reference immediately after the native create call.
            credential_secret = None

            if plan.delayed_auto_start:
                if self.journal is not None:
                    self.journal.append(
                        journal_id,
                        state=(
                            WindowsScmInstallJournalState
                            .CONFIGURE_INTENT_RECORDED
                        ),
                        occurred_at=now,
                    )
                self.backend.configure_delayed_auto_start(
                    service_handle,
                    True,
                )
                steps.append("delayed_auto_start_configured")
                if self.journal is not None:
                    self.journal.append(
                        journal_id,
                        state=(
                            WindowsScmInstallJournalState
                            .DELAYED_AUTO_START_CONFIGURED
                        ),
                        occurred_at=now,
                    )

            if self.journal is not None:
                self.journal.append(
                    journal_id,
                    state=WindowsScmInstallJournalState.COMPLETED,
                    occurred_at=now,
                )

            return WindowsScmInstallTransactionResult(
                authorization_id=consumed.authorization_id,
                service_name=target.service_name,
                manifest_sha256=target.manifest_sha256,
                binary_sha256=target.binary_sha256,
                registration_plan_sha256=(
                    target.registration_plan_sha256
                ),
                authorization_consumed_at=consumed.consumed_at or now,
                mutation_steps=tuple(steps),
                rollback_performed=False,
            )
        except Exception as exc:
            credential_secret = None
            if service_handle is not None:
                if self.journal is not None:
                    try:
                        self.journal.append(
                            journal_id,
                            state=(
                                WindowsScmInstallJournalState
                                .ROLLBACK_DELETE_INTENT_RECORDED
                            ),
                            occurred_at=now,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    except Exception:
                        # Preserve rollback as the highest-value action.
                        # The prior non-terminal journal state remains
                        # fail-closed/ambiguous for recovery.
                        pass
                try:
                    self.backend.delete_service(service_handle)
                    steps.append("service_deleted_rollback")
                    rollback_performed = True
                    if self.journal is not None:
                        try:
                            self.journal.append(
                                journal_id,
                                state=WindowsScmInstallJournalState.ROLLED_BACK,
                                occurred_at=now,
                            )
                        except Exception:
                            pass
                except Exception as rollback_exc:
                    rollback_error = (
                        f"{type(rollback_exc).__name__}: {rollback_exc}"
                    )
                    steps.append("service_delete_rollback_failed")
                    if self.journal is not None:
                        try:
                            self.journal.append(
                                journal_id,
                                state=(
                                    WindowsScmInstallJournalState
                                    .ROLLBACK_FAILED
                                ),
                                occurred_at=now,
                                error=rollback_error,
                            )
                        except Exception:
                            pass
            elif self.journal is not None:
                try:
                    self.journal.append(
                        journal_id,
                        state=WindowsScmInstallJournalState.FAILED,
                        occurred_at=now,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:
                    pass
            raise WindowsScmInstallationTransactionError(
                f"{type(exc).__name__}: {exc}",
                mutation_steps=tuple(steps),
                rollback_performed=rollback_performed,
                rollback_error=rollback_error,
            ) from exc
        finally:
            credential_secret = None
            if service_handle is not None:
                self.backend.close_handle(service_handle)
            if scm_handle is not None:
                self.backend.close_handle(scm_handle)
