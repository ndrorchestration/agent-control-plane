"""Fail-closed Windows SCM service-registration manifest.

This module defines and admits registration intent only. It does not call SCM,
create a service, store credentials, or establish reboot persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import hashlib
import json
import ntpath
import re
from pathlib import PureWindowsPath
from typing import Optional

from .authority import AuthorityValidationError


WINDOWS_SCM_REGISTRATION_SCHEMA_VERSION = (
    "agent-control-plane.windows-scm-registration.v0-candidate"
)

_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,256}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_SYSTEM_NAMES = {
    "localsystem",
    "system",
    "nt authority\\system",
}


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _service_name(value: str, field_name: str) -> str:
    normalized = _required(value, field_name)
    if not _SERVICE_NAME_RE.fullmatch(normalized):
        raise AuthorityValidationError(
            f"{field_name} contains unsupported characters"
        )
    return normalized


def _windows_path(value: str, field_name: str) -> str:
    raw = _required(value, field_name)
    path = PureWindowsPath(raw)
    if not path.is_absolute():
        raise AuthorityValidationError(
            f"{field_name} must be an absolute Windows path"
        )
    return ntpath.normcase(ntpath.normpath(str(path)))


def _account(value: str) -> str:
    return _required(value, "account_name")


class WindowsScmServiceStartType(IntEnum):
    AUTO_START = 0x00000002
    DEMAND_START = 0x00000003
    DISABLED = 0x00000004


@dataclass(frozen=True)
class WindowsScmServiceRegistrationManifest:
    service_name: str
    display_name: str
    binary_path: str
    account_name: str
    start_type: WindowsScmServiceStartType = (
        WindowsScmServiceStartType.DEMAND_START
    )
    description: str = ""
    dependencies: tuple[str, ...] = ()
    delayed_auto_start: bool = False
    credential_reference: Optional[str] = None
    binary_sha256: Optional[str] = None
    schema_version: str = WINDOWS_SCM_REGISTRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "service_name",
            _service_name(self.service_name, "service_name"),
        )
        object.__setattr__(
            self,
            "display_name",
            _required(self.display_name, "display_name"),
        )
        object.__setattr__(
            self,
            "binary_path",
            _windows_path(self.binary_path, "binary_path"),
        )
        object.__setattr__(
            self,
            "account_name",
            _account(self.account_name),
        )
        if not isinstance(self.start_type, WindowsScmServiceStartType):
            raise AuthorityValidationError(
                "start_type must be WindowsScmServiceStartType"
            )
        if not isinstance(self.description, str):
            raise AuthorityValidationError("description must be a string")
        if not isinstance(self.dependencies, tuple):
            raise AuthorityValidationError("dependencies must be a tuple")
        normalized_dependencies = tuple(
            _service_name(value, "dependency")
            for value in self.dependencies
        )
        if len(set(value.lower() for value in normalized_dependencies)) != len(
            normalized_dependencies
        ):
            raise AuthorityValidationError(
                "dependencies must not contain duplicates"
            )
        if any(
            value.lower() == self.service_name.lower()
            for value in normalized_dependencies
        ):
            raise AuthorityValidationError(
                "service must not depend on itself"
            )
        object.__setattr__(
            self,
            "dependencies",
            normalized_dependencies,
        )
        if not isinstance(self.delayed_auto_start, bool):
            raise AuthorityValidationError(
                "delayed_auto_start must be bool"
            )
        if (
            self.delayed_auto_start
            and self.start_type is not WindowsScmServiceStartType.AUTO_START
        ):
            raise AuthorityValidationError(
                "delayed_auto_start requires AUTO_START"
            )
        if self.credential_reference is not None:
            object.__setattr__(
                self,
                "credential_reference",
                _required(
                    self.credential_reference,
                    "credential_reference",
                ),
            )
        if self.binary_sha256 is not None:
            digest = _required(self.binary_sha256, "binary_sha256").lower()
            if not _SHA256_RE.fullmatch(digest):
                raise AuthorityValidationError(
                    "binary_sha256 must be 64 lowercase hex characters"
                )
            object.__setattr__(self, "binary_sha256", digest)
        if self.schema_version != WINDOWS_SCM_REGISTRATION_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema_version,
            "service_name": self.service_name,
            "display_name": self.display_name,
            "binary_path": self.binary_path,
            "account_name": self.account_name,
            "start_type": int(self.start_type),
            "description": self.description,
            "dependencies": list(self.dependencies),
            "delayed_auto_start": self.delayed_auto_start,
            "credential_reference": self.credential_reference,
            "binary_sha256": self.binary_sha256,
        }

    def content_sha256(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WindowsScmServiceRegistrationPolicy:
    """Admission policy for SCM registration intent before privileged mutation."""

    allowed_binary_paths: tuple[str, ...]
    allowed_accounts: tuple[str, ...]
    allowed_start_types: tuple[WindowsScmServiceStartType, ...] = (
        WindowsScmServiceStartType.DEMAND_START,
    )
    allowed_manifest_sha256: tuple[str, ...] = ()
    allow_local_system: bool = False
    allow_delayed_auto_start: bool = False
    require_binary_sha256: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.allowed_binary_paths, tuple)
            or not self.allowed_binary_paths
        ):
            raise AuthorityValidationError(
                "allowed_binary_paths must be a non-empty tuple"
            )
        object.__setattr__(
            self,
            "allowed_binary_paths",
            tuple(
                _windows_path(value, "allowed_binary_path")
                for value in self.allowed_binary_paths
            ),
        )
        if (
            not isinstance(self.allowed_accounts, tuple)
            or not self.allowed_accounts
        ):
            raise AuthorityValidationError(
                "allowed_accounts must be a non-empty tuple"
            )
        object.__setattr__(
            self,
            "allowed_accounts",
            tuple(
                _account(value).lower()
                for value in self.allowed_accounts
            ),
        )
        if (
            not isinstance(self.allowed_start_types, tuple)
            or not self.allowed_start_types
            or not all(
                isinstance(value, WindowsScmServiceStartType)
                for value in self.allowed_start_types
            )
        ):
            raise AuthorityValidationError(
                "allowed_start_types must contain WindowsScmServiceStartType"
            )
        if len(set(self.allowed_start_types)) != len(
            self.allowed_start_types
        ):
            raise AuthorityValidationError(
                "allowed_start_types must not contain duplicates"
            )
        if not isinstance(self.allowed_manifest_sha256, tuple):
            raise AuthorityValidationError(
                "allowed_manifest_sha256 must be a tuple"
            )
        for digest in self.allowed_manifest_sha256:
            if not _SHA256_RE.fullmatch(digest):
                raise AuthorityValidationError(
                    "allowed manifest SHA-256 must be lowercase hex"
                )
        for value, field_name in (
            (self.allow_local_system, "allow_local_system"),
            (self.allow_delayed_auto_start, "allow_delayed_auto_start"),
            (self.require_binary_sha256, "require_binary_sha256"),
        ):
            if not isinstance(value, bool):
                raise AuthorityValidationError(
                    f"{field_name} must be bool"
                )

    def assert_admitted(
        self,
        manifest: WindowsScmServiceRegistrationManifest,
    ) -> str:
        if not isinstance(
            manifest,
            WindowsScmServiceRegistrationManifest,
        ):
            raise AuthorityValidationError(
                "manifest must be WindowsScmServiceRegistrationManifest"
            )
        if manifest.binary_path not in self.allowed_binary_paths:
            raise AuthorityValidationError(
                "Windows service binary path not admitted"
            )
        account = manifest.account_name.lower()
        if account not in self.allowed_accounts:
            raise AuthorityValidationError(
                "Windows service account not admitted"
            )
        if (
            account in _LOCAL_SYSTEM_NAMES
            and not self.allow_local_system
        ):
            raise AuthorityValidationError(
                "LocalSystem service account not admitted"
            )
        if manifest.start_type not in self.allowed_start_types:
            raise AuthorityValidationError(
                "Windows service start type not admitted"
            )
        if (
            manifest.delayed_auto_start
            and not self.allow_delayed_auto_start
        ):
            raise AuthorityValidationError(
                "delayed auto-start not admitted"
            )
        if self.require_binary_sha256 and manifest.binary_sha256 is None:
            raise AuthorityValidationError(
                "binary_sha256 is required for registration admission"
            )

        digest = manifest.content_sha256()
        if (
            self.allowed_manifest_sha256
            and digest not in self.allowed_manifest_sha256
        ):
            raise AuthorityValidationError(
                "Windows service registration manifest not admitted"
            )
        return digest
