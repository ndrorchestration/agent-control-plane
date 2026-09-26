"""Read-only recovery reconciliation for interrupted Windows SCM installs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import hashlib
from typing import Optional, Protocol, runtime_checkable

from .authority import AuthorityValidationError
from .windows_scm_install_authorization import WindowsScmInstallationTarget
from .windows_scm_install_journal import (
    WindowsScmInstallJournalRecord,
    WindowsScmInstallRecoveryDisposition,
)
from .windows_scm_registration_plan import (
    WindowsScmServiceRegistrationPlan,
)


@dataclass(frozen=True)
class WindowsScmObservedService:
    service_name: str
    display_name: str
    binary_path_command: str
    service_type: int
    start_type: int
    error_control: int
    dependencies_multi_sz: Optional[str]
    account_name: str


class WindowsScmInspectionMatch(str, Enum):
    ABSENT = "absent"
    EXACT_MATCH = "exact_match"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class WindowsScmInspectionResult:
    match: WindowsScmInspectionMatch
    observed: Optional[WindowsScmObservedService]
    binary_sha256: Optional[str]
    mismatches: tuple[str, ...]


@runtime_checkable
class WindowsScmReadOnlyInspector(Protocol):
    def inspect(
        self,
        service_name: str,
    ) -> Optional[WindowsScmObservedService]: ...


class WindowsScmInstallRecoveryDecision(str, Enum):
    CLEAN_INSTALLED = "clean_installed"
    CLEAN_ROLLED_BACK = "clean_rolled_back"
    NEW_INSTALL_AUTH_REQUIRED = "new_install_auth_required"
    HOLD_EXACT_SERVICE_PRESENT = "hold_exact_service_present"
    HOLD_IDENTITY_CONFLICT = "hold_identity_conflict"
    HOLD_EXPECTED_SERVICE_MISSING = "hold_expected_service_missing"


@dataclass(frozen=True)
class WindowsScmInstallRecoveryResolution:
    decision: WindowsScmInstallRecoveryDecision
    journal_disposition: WindowsScmInstallRecoveryDisposition
    inspection: WindowsScmInspectionResult
    cleanup_mutation_authorized: bool = False


def _binary_path_from_command(command: str) -> str:
    if not isinstance(command, str) or not command.strip():
        raise AuthorityValidationError(
            "binary_path_command must not be blank"
        )
    value = command.strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        if end <= 1:
            raise AuthorityValidationError(
                "quoted binary_path_command is malformed"
            )
        return value[1:end]
    return value.split(" ", 1)[0]


def _sha256_file(path: str) -> str:
    item = Path(path)
    if not item.exists() or not item.is_file():
        raise AuthorityValidationError(
            "observed Windows service binary is unavailable"
        )
    digest = hashlib.sha256()
    with item.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class WindowsScmInstallRecoveryInspector:
    """Compare live read-only SCM state to an exact admitted install target."""

    def __init__(
        self,
        *,
        inspector: WindowsScmReadOnlyInspector,
        binary_hasher=_sha256_file,
    ) -> None:
        if not isinstance(inspector, WindowsScmReadOnlyInspector):
            raise AuthorityValidationError(
                "inspector must implement WindowsScmReadOnlyInspector"
            )
        if not callable(binary_hasher):
            raise AuthorityValidationError(
                "binary_hasher must be callable"
            )
        self.inspector = inspector
        self.binary_hasher = binary_hasher

    def inspect_exact(
        self,
        *,
        target: WindowsScmInstallationTarget,
        plan: WindowsScmServiceRegistrationPlan,
    ) -> WindowsScmInspectionResult:
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
                "recovery plan service name does not match target"
            )

        observed = self.inspector.inspect(target.service_name)
        if observed is None:
            return WindowsScmInspectionResult(
                match=WindowsScmInspectionMatch.ABSENT,
                observed=None,
                binary_sha256=None,
                mismatches=(),
            )

        mismatches: list[str] = []
        comparisons = (
            ("service_name", observed.service_name, plan.service_name),
            ("display_name", observed.display_name, plan.display_name),
            (
                "binary_path_command",
                observed.binary_path_command,
                plan.binary_path_command,
            ),
            ("service_type", observed.service_type, plan.service_type),
            ("start_type", observed.start_type, plan.start_type),
            ("error_control", observed.error_control, plan.error_control),
            (
                "dependencies_multi_sz",
                observed.dependencies_multi_sz,
                plan.dependencies_multi_sz,
            ),
            ("account_name", observed.account_name, plan.account_name),
        )
        for name, actual, expected in comparisons:
            if actual != expected:
                mismatches.append(name)

        binary_sha256: Optional[str] = None
        try:
            binary_path = _binary_path_from_command(
                observed.binary_path_command
            )
            binary_sha256 = self.binary_hasher(binary_path)
        except Exception:
            mismatches.append("binary_sha256_unavailable")
        else:
            if binary_sha256 != target.binary_sha256:
                mismatches.append("binary_sha256")

        return WindowsScmInspectionResult(
            match=(
                WindowsScmInspectionMatch.EXACT_MATCH
                if not mismatches
                else WindowsScmInspectionMatch.MISMATCH
            ),
            observed=observed,
            binary_sha256=binary_sha256,
            mismatches=tuple(mismatches),
        )


class WindowsScmInstallRecoveryResolver:
    """Produce a fail-closed decision from durable journal + live inspection."""

    def resolve(
        self,
        *,
        journal_record: WindowsScmInstallJournalRecord,
        journal_disposition: WindowsScmInstallRecoveryDisposition,
        inspection: WindowsScmInspectionResult,
    ) -> WindowsScmInstallRecoveryResolution:
        if not isinstance(journal_record, WindowsScmInstallJournalRecord):
            raise AuthorityValidationError(
                "journal_record must be WindowsScmInstallJournalRecord"
            )
        if not isinstance(
            journal_disposition,
            WindowsScmInstallRecoveryDisposition,
        ):
            raise AuthorityValidationError(
                "journal_disposition must be WindowsScmInstallRecoveryDisposition"
            )
        if not isinstance(inspection, WindowsScmInspectionResult):
            raise AuthorityValidationError(
                "inspection must be WindowsScmInspectionResult"
            )

        if inspection.match is WindowsScmInspectionMatch.MISMATCH:
            decision = WindowsScmInstallRecoveryDecision.HOLD_IDENTITY_CONFLICT
        elif (
            journal_disposition
            is WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED
        ):
            decision = (
                WindowsScmInstallRecoveryDecision.CLEAN_INSTALLED
                if inspection.match is WindowsScmInspectionMatch.EXACT_MATCH
                else WindowsScmInstallRecoveryDecision.HOLD_EXPECTED_SERVICE_MISSING
            )
        elif (
            journal_disposition
            is WindowsScmInstallRecoveryDisposition.CLEAN_ROLLED_BACK
        ):
            decision = (
                WindowsScmInstallRecoveryDecision.CLEAN_ROLLED_BACK
                if inspection.match is WindowsScmInspectionMatch.ABSENT
                else WindowsScmInstallRecoveryDecision.HOLD_EXACT_SERVICE_PRESENT
            )
        elif journal_disposition in (
            WindowsScmInstallRecoveryDisposition.SAFE_PRE_MUTATION,
            WindowsScmInstallRecoveryDisposition.NO_SERVICE_MUTATION_NEEDS_NEW_AUTH,
        ):
            decision = (
                WindowsScmInstallRecoveryDecision.NEW_INSTALL_AUTH_REQUIRED
                if inspection.match is WindowsScmInspectionMatch.ABSENT
                else WindowsScmInstallRecoveryDecision.HOLD_EXACT_SERVICE_PRESENT
            )
        else:
            decision = (
                WindowsScmInstallRecoveryDecision.NEW_INSTALL_AUTH_REQUIRED
                if inspection.match is WindowsScmInspectionMatch.ABSENT
                else WindowsScmInstallRecoveryDecision.HOLD_EXACT_SERVICE_PRESENT
            )

        return WindowsScmInstallRecoveryResolution(
            decision=decision,
            journal_disposition=journal_disposition,
            inspection=inspection,
            cleanup_mutation_authorized=False,
        )
