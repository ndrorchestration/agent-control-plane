"""Declarative process-boundary assessment for the experimental mutation executor.

This module does not attest a process. It records and validates the controls
that would be required for ordinary local testing versus a future higher-
assurance deployment boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path
from typing import Iterable

EXECUTOR_PROCESS_BOUNDARY_SCHEMA_VERSION = (
    "agent-control-plane.executor-process-boundary.v0-candidate"
)


class ExecutorProcessBoundaryError(ValueError):
    pass


class ExecutorAssuranceTarget(str, Enum):
    LOCAL_TEST = "local_test"
    HIGH_ASSURANCE = "high_assurance"


@dataclass(frozen=True)
class ExecutorProcessBoundaryEvidence:
    executable_path: str
    executable_sha256: str
    os_user: str
    repository_roots: tuple[str, ...]
    authorization_store_path: str
    journal_store_path: str
    rollback_custody_path: str
    dedicated_service_identity: bool = False
    trusted_launcher_identity: bool = False
    acl_separation_verified: bool = False
    os_isolation_verified: bool = False
    peer_process_tamper_resistance_verified: bool = False

    def __post_init__(self) -> None:
        exe = Path(self.executable_path)
        if not exe.is_absolute():
            raise ExecutorProcessBoundaryError("executable_path must be absolute")
        if len(self.executable_sha256) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.executable_sha256
        ):
            raise ExecutorProcessBoundaryError(
                "executable_sha256 must be lowercase sha256"
            )
        if not isinstance(self.os_user, str) or not self.os_user.strip():
            raise ExecutorProcessBoundaryError("os_user must not be blank")
        if not self.repository_roots:
            raise ExecutorProcessBoundaryError(
                "at least one repository root is required"
            )
        for root in self.repository_roots:
            if not Path(root).is_absolute():
                raise ExecutorProcessBoundaryError("repository roots must be absolute")
        for field_name in (
            "authorization_store_path",
            "journal_store_path",
            "rollback_custody_path",
        ):
            value = getattr(self, field_name)
            if not Path(value).is_absolute():
                raise ExecutorProcessBoundaryError(f"{field_name} must be absolute")


@dataclass(frozen=True)
class ExecutorProcessBoundaryAssessment:
    target: ExecutorAssuranceTarget
    admitted: bool
    reasons: tuple[str, ...]
    executable_identity_recorded: bool
    store_paths_separated: bool
    service_identity_verified: bool
    trusted_launcher_verified: bool
    acl_separation_verified: bool
    os_isolation_verified: bool
    peer_process_tamper_resistance_verified: bool
    schema_version: str = EXECUTOR_PROCESS_BOUNDARY_SCHEMA_VERSION


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_path_set(values: Iterable[str]) -> set[str]:
    return {str(Path(value).resolve(strict=False)) for value in values}


def assess_executor_process_boundary(
    evidence: ExecutorProcessBoundaryEvidence,
    *,
    target: ExecutorAssuranceTarget,
) -> ExecutorProcessBoundaryAssessment:
    if not isinstance(evidence, ExecutorProcessBoundaryEvidence):
        raise TypeError("evidence must be ExecutorProcessBoundaryEvidence")
    if not isinstance(target, ExecutorAssuranceTarget):
        raise TypeError("target must be ExecutorAssuranceTarget")

    executable_identity_recorded = bool(
        evidence.executable_path and evidence.executable_sha256
    )

    stores = _normalized_path_set(
        (
            evidence.authorization_store_path,
            evidence.journal_store_path,
            evidence.rollback_custody_path,
        )
    )
    roots = _normalized_path_set(evidence.repository_roots)
    store_paths_separated = len(stores) == 3 and stores.isdisjoint(roots)

    reasons: list[str] = []
    if not executable_identity_recorded:
        reasons.append("executable identity missing")
    if not store_paths_separated:
        reasons.append("store/repository path separation not established")

    if target is ExecutorAssuranceTarget.HIGH_ASSURANCE:
        required = {
            "dedicated service identity": evidence.dedicated_service_identity,
            "trusted launcher identity": evidence.trusted_launcher_identity,
            "ACL separation": evidence.acl_separation_verified,
            "OS isolation": evidence.os_isolation_verified,
            "peer-process tamper resistance": (
                evidence.peer_process_tamper_resistance_verified
            ),
        }
        reasons.extend(
            f"{name} not established" for name, passed in required.items() if not passed
        )

    admitted = not reasons
    return ExecutorProcessBoundaryAssessment(
        target=target,
        admitted=admitted,
        reasons=tuple(reasons),
        executable_identity_recorded=executable_identity_recorded,
        store_paths_separated=store_paths_separated,
        service_identity_verified=evidence.dedicated_service_identity,
        trusted_launcher_verified=evidence.trusted_launcher_identity,
        acl_separation_verified=evidence.acl_separation_verified,
        os_isolation_verified=evidence.os_isolation_verified,
        peer_process_tamper_resistance_verified=(
            evidence.peer_process_tamper_resistance_verified
        ),
    )
