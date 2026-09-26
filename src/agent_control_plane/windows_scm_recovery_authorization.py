"""Exact, expiring, single-use authorization for Windows SCM recovery mutation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_install_journal import (
    WindowsScmInstallJournalRecord,
    WindowsScmInstallRecoveryAssessment,
    WindowsScmInstallRecoveryDisposition,
)
from .windows_scm_recovery_inspector import (
    WindowsScmInstallRecoveryInspection,
    WindowsScmLiveServiceConfig,
    WindowsScmRecoveryResolution,
)


WINDOWS_SCM_RECOVERY_AUTHORIZATION_SCHEMA_VERSION = (
    "agent-control-plane.windows-scm-recovery-authorization.v0-candidate"
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


class WindowsScmRecoveryAction(str, Enum):
    DELETE_EXACT_SERVICE = "delete_exact_service"


def windows_scm_live_config_sha256(
    live: WindowsScmLiveServiceConfig,
) -> str:
    if not isinstance(live, WindowsScmLiveServiceConfig):
        raise AuthorityValidationError(
            "live must be WindowsScmLiveServiceConfig"
        )
    payload = {
        "service_name": live.service_name,
        "service_type": live.service_type,
        "start_type": live.start_type,
        "error_control": live.error_control,
        "binary_path_command": live.binary_path_command,
        "dependencies": list(live.dependencies),
        "account_name": live.account_name,
        "display_name": live.display_name,
        "delayed_auto_start": live.delayed_auto_start,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WindowsScmRecoveryTarget:
    transaction_id: str
    service_name: str
    manifest_sha256: str
    binary_sha256: str
    registration_plan_sha256: str
    journal_state: str
    journal_disposition: str
    inspection_resolution: str
    live_config_sha256: str
    action: WindowsScmRecoveryAction


def build_windows_scm_recovery_target(
    *,
    journal_record: WindowsScmInstallJournalRecord,
    assessment: WindowsScmInstallRecoveryAssessment,
    inspection: WindowsScmInstallRecoveryInspection,
    action: WindowsScmRecoveryAction,
) -> WindowsScmRecoveryTarget:
    if not isinstance(journal_record, WindowsScmInstallJournalRecord):
        raise AuthorityValidationError(
            "journal_record must be WindowsScmInstallJournalRecord"
        )
    if not isinstance(assessment, WindowsScmInstallRecoveryAssessment):
        raise AuthorityValidationError(
            "assessment must be WindowsScmInstallRecoveryAssessment"
        )
    if not isinstance(inspection, WindowsScmInstallRecoveryInspection):
        raise AuthorityValidationError(
            "inspection must be WindowsScmInstallRecoveryInspection"
        )
    if not isinstance(action, WindowsScmRecoveryAction):
        raise AuthorityValidationError(
            "action must be WindowsScmRecoveryAction"
        )
    if journal_record.transaction_id != assessment.transaction_id:
        raise AuthorityValidationError(
            "recovery assessment transaction mismatch"
        )
    if inspection.journal_disposition is not assessment.disposition:
        raise AuthorityValidationError(
            "recovery inspection disposition mismatch"
        )
    if action is not WindowsScmRecoveryAction.DELETE_EXACT_SERVICE:
        raise AuthorityValidationError("unsupported recovery action")
    if assessment.disposition not in (
        WindowsScmInstallRecoveryDisposition.HOLD_POSSIBLE_INSTALLED_SERVICE,
        WindowsScmInstallRecoveryDisposition.HOLD_ROLLBACK_FAILED,
    ):
        raise AuthorityValidationError(
            "journal disposition does not permit recovery deletion authorization"
        )
    if inspection.resolution is not WindowsScmRecoveryResolution.INSTALLED_MATCH:
        raise AuthorityValidationError(
            "exact installed-match inspection required for recovery deletion"
        )
    if inspection.live_service is None:
        raise AuthorityValidationError(
            "live service evidence required for recovery deletion"
        )

    return WindowsScmRecoveryTarget(
        transaction_id=journal_record.transaction_id,
        service_name=journal_record.service_name,
        manifest_sha256=journal_record.manifest_sha256,
        binary_sha256=journal_record.binary_sha256,
        registration_plan_sha256=journal_record.registration_plan_sha256,
        journal_state=assessment.current_state.value,
        journal_disposition=assessment.disposition.value,
        inspection_resolution=inspection.resolution.value,
        live_config_sha256=windows_scm_live_config_sha256(
            inspection.live_service
        ),
        action=action,
    )


@dataclass(frozen=True)
class WindowsScmRecoveryAuthorization:
    authorization_id: str
    transaction_id: str
    service_name: str
    manifest_sha256: str
    binary_sha256: str
    registration_plan_sha256: str
    journal_state: str
    journal_disposition: str
    inspection_resolution: str
    live_config_sha256: str
    action: str
    authorized_by: str
    issued_at: str
    expires_at: str
    consumed_at: Optional[str] = None
    schema_version: str = (
        WINDOWS_SCM_RECOVERY_AUTHORIZATION_SCHEMA_VERSION
    )


class WindowsScmRecoveryAuthorizationStore:
    """SQLite-backed exact single-use authorization for recovery mutation."""

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
                CREATE TABLE IF NOT EXISTS windows_scm_recovery_authorization (
                    authorization_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    binary_sha256 TEXT NOT NULL,
                    registration_plan_sha256 TEXT NOT NULL,
                    journal_state TEXT NOT NULL,
                    journal_disposition TEXT NOT NULL,
                    inspection_resolution TEXT NOT NULL,
                    live_config_sha256 TEXT NOT NULL,
                    action TEXT NOT NULL,
                    authorized_by TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> WindowsScmRecoveryAuthorization:
        return WindowsScmRecoveryAuthorization(
            authorization_id=row["authorization_id"],
            transaction_id=row["transaction_id"],
            service_name=row["service_name"],
            manifest_sha256=row["manifest_sha256"],
            binary_sha256=row["binary_sha256"],
            registration_plan_sha256=row["registration_plan_sha256"],
            journal_state=row["journal_state"],
            journal_disposition=row["journal_disposition"],
            inspection_resolution=row["inspection_resolution"],
            live_config_sha256=row["live_config_sha256"],
            action=row["action"],
            authorized_by=row["authorized_by"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _target_tuple(target: WindowsScmRecoveryTarget):
        return (
            target.transaction_id,
            target.service_name,
            target.manifest_sha256,
            target.binary_sha256,
            target.registration_plan_sha256,
            target.journal_state,
            target.journal_disposition,
            target.inspection_resolution,
            target.live_config_sha256,
            target.action.value,
        )

    @staticmethod
    def _authorization_tuple(
        item: WindowsScmRecoveryAuthorization,
    ):
        return (
            item.transaction_id,
            item.service_name,
            item.manifest_sha256,
            item.binary_sha256,
            item.registration_plan_sha256,
            item.journal_state,
            item.journal_disposition,
            item.inspection_resolution,
            item.live_config_sha256,
            item.action,
        )

    def get(
        self,
        authorization_id: str,
    ) -> Optional[WindowsScmRecoveryAuthorization]:
        identifier = _required(authorization_id, "authorization_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM windows_scm_recovery_authorization
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
        return None if row is None else self._row(row)

    def issue(
        self,
        *,
        authorization_id: str,
        target: WindowsScmRecoveryTarget,
        authorized_by: str,
        issued_at: str,
        expires_at: str,
    ) -> WindowsScmRecoveryAuthorization:
        if not isinstance(target, WindowsScmRecoveryTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmRecoveryTarget"
            )
        issued = _canonical(issued_at, "issued_at")
        expires = _canonical(expires_at, "expires_at")
        if _utc(expires, "expires_at") <= _utc(issued, "issued_at"):
            raise AuthorityValidationError(
                "expires_at must be after issued_at"
            )
        authorization = WindowsScmRecoveryAuthorization(
            authorization_id=_required(
                authorization_id,
                "authorization_id",
            ),
            transaction_id=target.transaction_id,
            service_name=target.service_name,
            manifest_sha256=target.manifest_sha256,
            binary_sha256=target.binary_sha256,
            registration_plan_sha256=target.registration_plan_sha256,
            journal_state=target.journal_state,
            journal_disposition=target.journal_disposition,
            inspection_resolution=target.inspection_resolution,
            live_config_sha256=target.live_config_sha256,
            action=target.action.value,
            authorized_by=_required(authorized_by, "authorized_by"),
            issued_at=issued,
            expires_at=expires,
        )

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM windows_scm_recovery_authorization
                WHERE authorization_id = ?
                """,
                (authorization.authorization_id,),
            ).fetchone()
            if existing is not None:
                prior = self._row(existing)
                if prior == authorization:
                    return prior
                raise AuthorityValidationError(
                    "recovery authorization_id conflict"
                )
            connection.execute(
                """
                INSERT INTO windows_scm_recovery_authorization (
                    authorization_id, transaction_id, service_name,
                    manifest_sha256, binary_sha256,
                    registration_plan_sha256, journal_state,
                    journal_disposition, inspection_resolution,
                    live_config_sha256, action, authorized_by,
                    issued_at, expires_at, consumed_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    authorization.authorization_id,
                    authorization.transaction_id,
                    authorization.service_name,
                    authorization.manifest_sha256,
                    authorization.binary_sha256,
                    authorization.registration_plan_sha256,
                    authorization.journal_state,
                    authorization.journal_disposition,
                    authorization.inspection_resolution,
                    authorization.live_config_sha256,
                    authorization.action,
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
        target: WindowsScmRecoveryTarget,
        now: str,
    ) -> WindowsScmRecoveryAuthorization:
        if not isinstance(target, WindowsScmRecoveryTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmRecoveryTarget"
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
                SELECT * FROM windows_scm_recovery_authorization
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError(
                    "recovery authorization not found"
                )
            authorization = self._row(row)
            if authorization.consumed_at is not None:
                raise AuthorityValidationError(
                    "recovery authorization already consumed"
                )
            if _utc(canonical_now, "now") >= _utc(
                authorization.expires_at,
                "expires_at",
            ):
                raise AuthorityValidationError(
                    "recovery authorization expired"
                )
            if self._authorization_tuple(
                authorization
            ) != self._target_tuple(target):
                raise AuthorityValidationError(
                    "recovery authorization does not match target"
                )
            connection.execute(
                """
                UPDATE windows_scm_recovery_authorization
                SET consumed_at = ?
                WHERE authorization_id = ?
                """,
                (canonical_now, identifier),
            )

        result = self.get(identifier)
        assert result is not None
        return result
