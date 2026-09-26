"""Exact, expiring, single-use authorization for Windows service installation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_binary_verification import (
    WindowsScmRegistrationAdmissionResult,
)
from .windows_scm_registration import (
    WindowsScmServiceRegistrationManifest,
)
from .windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)


WINDOWS_SCM_INSTALL_AUTHORIZATION_SCHEMA_VERSION = (
    "agent-control-plane.windows-scm-install-authorization.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _utc(value: str, field_name: str) -> datetime:
    raw = _required(value, field_name)
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AuthorityValidationError(
            f"{field_name} must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(
            f"{field_name} must be timezone-aware UTC"
        )
    if parsed.utcoffset() != timedelta(0):
        raise AuthorityValidationError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc)


def _canonical(value: str, field_name: str) -> str:
    return _utc(value, field_name).isoformat().replace("+00:00", "Z")


def windows_scm_registration_plan_sha256(
    plan: WindowsScmServiceRegistrationPlan,
) -> str:
    if not isinstance(plan, WindowsScmServiceRegistrationPlan):
        raise AuthorityValidationError(
            "plan must be WindowsScmServiceRegistrationPlan"
        )
    payload = {
        "manifest_sha256": plan.manifest_sha256,
        "service_name": plan.service_name,
        "display_name": plan.display_name,
        "binary_path_command": plan.binary_path_command,
        "service_type": plan.service_type,
        "start_type": plan.start_type,
        "error_control": plan.error_control,
        "dependencies_multi_sz": plan.dependencies_multi_sz,
        "account_name": plan.account_name,
        "credential_reference": plan.credential_reference,
        "requires_credential_resolution": (
            plan.requires_credential_resolution
        ),
        "delayed_auto_start": plan.delayed_auto_start,
        "desired_scm_access": plan.desired_scm_access,
        "desired_service_access": plan.desired_service_access,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WindowsScmInstallationTarget:
    service_name: str
    manifest_sha256: str
    binary_sha256: str
    registration_plan_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "service_name",
            _required(self.service_name, "service_name"),
        )
        for field_name in (
            "manifest_sha256",
            "binary_sha256",
            "registration_plan_sha256",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or len(value) != 64:
                raise AuthorityValidationError(
                    f"{field_name} must be a SHA-256 hex digest"
                )
            try:
                bytes.fromhex(value)
            except ValueError as exc:
                raise AuthorityValidationError(
                    f"{field_name} must be hexadecimal"
                ) from exc


def build_windows_scm_installation_target(
    *,
    manifest: WindowsScmServiceRegistrationManifest,
    admission: WindowsScmRegistrationAdmissionResult,
    plan: WindowsScmServiceRegistrationPlan,
) -> WindowsScmInstallationTarget:
    if not isinstance(
        manifest,
        WindowsScmServiceRegistrationManifest,
    ):
        raise AuthorityValidationError(
            "manifest must be WindowsScmServiceRegistrationManifest"
        )
    if not isinstance(
        admission,
        WindowsScmRegistrationAdmissionResult,
    ):
        raise AuthorityValidationError(
            "admission must be WindowsScmRegistrationAdmissionResult"
        )
    if not isinstance(plan, WindowsScmServiceRegistrationPlan):
        raise AuthorityValidationError(
            "plan must be WindowsScmServiceRegistrationPlan"
        )

    manifest_sha256 = manifest.content_sha256()
    if admission.manifest_sha256 != manifest_sha256:
        raise AuthorityValidationError(
            "registration admission manifest identity mismatch"
        )
    if plan.manifest_sha256 != manifest_sha256:
        raise AuthorityValidationError(
            "registration plan manifest identity mismatch"
        )
    if plan.service_name != manifest.service_name:
        raise AuthorityValidationError(
            "registration plan service name mismatch"
        )
    if admission.binary.expected_sha256 != manifest.binary_sha256:
        raise AuthorityValidationError(
            "verified binary identity does not match manifest"
        )
    if admission.binary.actual_sha256 != manifest.binary_sha256:
        raise AuthorityValidationError(
            "actual binary identity does not match manifest"
        )

    return WindowsScmInstallationTarget(
        service_name=manifest.service_name,
        manifest_sha256=manifest_sha256,
        binary_sha256=admission.binary.actual_sha256,
        registration_plan_sha256=windows_scm_registration_plan_sha256(plan),
    )


@dataclass(frozen=True)
class WindowsScmInstallationAuthorization:
    authorization_id: str
    service_name: str
    manifest_sha256: str
    binary_sha256: str
    registration_plan_sha256: str
    authorized_by: str
    issued_at: str
    expires_at: str
    consumed_at: Optional[str] = None
    schema_version: str = (
        WINDOWS_SCM_INSTALL_AUTHORIZATION_SCHEMA_VERSION
    )

    def __post_init__(self) -> None:
        for field_name in (
            "authorization_id",
            "service_name",
            "authorized_by",
        ):
            object.__setattr__(
                self,
                field_name,
                _required(getattr(self, field_name), field_name),
            )
        for field_name in (
            "manifest_sha256",
            "binary_sha256",
            "registration_plan_sha256",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or len(value) != 64:
                raise AuthorityValidationError(
                    f"{field_name} must be a SHA-256 hex digest"
                )
            try:
                bytes.fromhex(value)
            except ValueError as exc:
                raise AuthorityValidationError(
                    f"{field_name} must be hexadecimal"
                ) from exc
        object.__setattr__(
            self,
            "issued_at",
            _canonical(self.issued_at, "issued_at"),
        )
        object.__setattr__(
            self,
            "expires_at",
            _canonical(self.expires_at, "expires_at"),
        )
        if _utc(self.expires_at, "expires_at") <= _utc(
            self.issued_at,
            "issued_at",
        ):
            raise AuthorityValidationError(
                "expires_at must be after issued_at"
            )
        if self.consumed_at is not None:
            object.__setattr__(
                self,
                "consumed_at",
                _canonical(self.consumed_at, "consumed_at"),
            )
        if (
            self.schema_version
            != WINDOWS_SCM_INSTALL_AUTHORIZATION_SCHEMA_VERSION
        ):
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )


class WindowsScmInstallationAuthorizationStore:
    """SQLite-backed exact single-use Windows installation authorization."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS windows_scm_install_authorization (
                    authorization_id TEXT PRIMARY KEY,
                    service_name TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    binary_sha256 TEXT NOT NULL,
                    registration_plan_sha256 TEXT NOT NULL,
                    authorized_by TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def _row(
        self,
        row: sqlite3.Row,
    ) -> WindowsScmInstallationAuthorization:
        return WindowsScmInstallationAuthorization(
            authorization_id=row["authorization_id"],
            service_name=row["service_name"],
            manifest_sha256=row["manifest_sha256"],
            binary_sha256=row["binary_sha256"],
            registration_plan_sha256=row[
                "registration_plan_sha256"
            ],
            authorized_by=row["authorized_by"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            schema_version=row["schema_version"],
        )

    def get(
        self,
        authorization_id: str,
    ) -> Optional[WindowsScmInstallationAuthorization]:
        identifier = _required(
            authorization_id,
            "authorization_id",
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM windows_scm_install_authorization
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
        return None if row is None else self._row(row)

    def issue(
        self,
        *,
        authorization_id: str,
        target: WindowsScmInstallationTarget,
        authorized_by: str,
        issued_at: str,
        expires_at: str,
    ) -> WindowsScmInstallationAuthorization:
        if not isinstance(target, WindowsScmInstallationTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmInstallationTarget"
            )
        authorization = WindowsScmInstallationAuthorization(
            authorization_id=_required(
                authorization_id,
                "authorization_id",
            ),
            service_name=target.service_name,
            manifest_sha256=target.manifest_sha256,
            binary_sha256=target.binary_sha256,
            registration_plan_sha256=target.registration_plan_sha256,
            authorized_by=_required(authorized_by, "authorized_by"),
            issued_at=issued_at,
            expires_at=expires_at,
        )

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM windows_scm_install_authorization
                WHERE authorization_id = ?
                """,
                (authorization.authorization_id,),
            ).fetchone()
            if existing is not None:
                prior = self._row(existing)
                if prior == authorization:
                    return prior
                raise AuthorityValidationError(
                    "installation authorization_id conflict"
                )
            connection.execute(
                """
                INSERT INTO windows_scm_install_authorization (
                    authorization_id,
                    service_name,
                    manifest_sha256,
                    binary_sha256,
                    registration_plan_sha256,
                    authorized_by,
                    issued_at,
                    expires_at,
                    consumed_at,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    authorization.authorization_id,
                    authorization.service_name,
                    authorization.manifest_sha256,
                    authorization.binary_sha256,
                    authorization.registration_plan_sha256,
                    authorization.authorized_by,
                    authorization.issued_at,
                    authorization.expires_at,
                    authorization.schema_version,
                ),
            )
        result = self.get(authorization.authorization_id)
        assert result is not None
        return result

    def consume(
        self,
        authorization_id: str,
        *,
        target: WindowsScmInstallationTarget,
        now: str,
    ) -> WindowsScmInstallationAuthorization:
        if not isinstance(target, WindowsScmInstallationTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmInstallationTarget"
            )
        identifier = _required(
            authorization_id,
            "authorization_id",
        )
        canonical_now = _canonical(now, "now")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM windows_scm_install_authorization
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError(
                    "installation authorization not found"
                )
            authorization = self._row(row)
            if authorization.consumed_at is not None:
                raise AuthorityValidationError(
                    "installation authorization already consumed"
                )
            if _utc(canonical_now, "now") >= _utc(
                authorization.expires_at,
                "expires_at",
            ):
                raise AuthorityValidationError(
                    "installation authorization expired"
                )

            actual = (
                authorization.service_name,
                authorization.manifest_sha256,
                authorization.binary_sha256,
                authorization.registration_plan_sha256,
            )
            expected = (
                target.service_name,
                target.manifest_sha256,
                target.binary_sha256,
                target.registration_plan_sha256,
            )
            if actual != expected:
                raise AuthorityValidationError(
                    "installation authorization does not match target"
                )

            connection.execute(
                """
                UPDATE windows_scm_install_authorization
                SET consumed_at = ?
                WHERE authorization_id = ?
                """,
                (canonical_now, identifier),
            )

        result = self.get(identifier)
        assert result is not None
        return result
