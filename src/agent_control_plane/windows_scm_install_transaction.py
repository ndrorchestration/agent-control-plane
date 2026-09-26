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
        self.authorization_store = authorization_store
        self.backend = backend
        self.credential_resolver = credential_resolver

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
    ) -> WindowsScmInstallTransactionResult:
        self._validate_exact_target(target=target, plan=plan)

        # Exact single-use authorization is consumed before any backend call.
        consumed = self.authorization_store.consume(
            authorization_id,
            target=target,
            now=now,
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

            service_handle = self.backend.create_service(
                scm_handle,
                plan,
                credential_secret,
            )
            steps.append("service_created")

            # Drop the reference immediately after the native create call.
            credential_secret = None

            if plan.delayed_auto_start:
                self.backend.configure_delayed_auto_start(
                    service_handle,
                    True,
                )
                steps.append("delayed_auto_start_configured")

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
                try:
                    self.backend.delete_service(service_handle)
                    steps.append("service_deleted_rollback")
                    rollback_performed = True
                except Exception as rollback_exc:
                    rollback_error = (
                        f"{type(rollback_exc).__name__}: {rollback_exc}"
                    )
                    steps.append("service_delete_rollback_failed")
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
