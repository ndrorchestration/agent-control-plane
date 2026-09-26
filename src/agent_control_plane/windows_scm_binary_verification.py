"""Fail-closed on-disk binary verification for Windows service registration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_registration import (
    WindowsScmServiceRegistrationManifest,
    WindowsScmServiceRegistrationPolicy,
)


@dataclass(frozen=True)
class WindowsScmBinaryVerification:
    binary_path: str
    expected_sha256: str
    actual_sha256: str
    size_bytes: int
    modified_time_ns: int

    @property
    def matched(self) -> bool:
        return self.expected_sha256 == self.actual_sha256


@dataclass(frozen=True)
class WindowsScmRegistrationAdmissionResult:
    manifest_sha256: str
    binary: WindowsScmBinaryVerification


class WindowsScmBinaryVerifier:
    """Hash the actual service binary and require an exact manifest match."""

    def __init__(self, *, chunk_size: int = 1024 * 1024) -> None:
        if (
            isinstance(chunk_size, bool)
            or not isinstance(chunk_size, int)
            or chunk_size < 1
        ):
            raise AuthorityValidationError(
                "chunk_size must be an integer >= 1"
            )
        self.chunk_size = chunk_size

    def verify(
        self,
        manifest: WindowsScmServiceRegistrationManifest,
    ) -> WindowsScmBinaryVerification:
        if not isinstance(
            manifest,
            WindowsScmServiceRegistrationManifest,
        ):
            raise AuthorityValidationError(
                "manifest must be WindowsScmServiceRegistrationManifest"
            )
        if manifest.binary_sha256 is None:
            raise AuthorityValidationError(
                "binary_sha256 is required for on-disk verification"
            )
        if os.name != "nt":
            raise AuthorityValidationError(
                "on-disk Windows service binary verification requires Windows"
            )

        path = Path(manifest.binary_path)
        if not path.exists():
            raise AuthorityValidationError(
                "Windows service binary does not exist"
            )
        if not path.is_file():
            raise AuthorityValidationError(
                "Windows service binary path is not a file"
            )

        before = path.stat()
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(self.chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        after = path.stat()

        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise AuthorityValidationError(
                "Windows service binary changed during verification"
            )
        if size != after.st_size:
            raise AuthorityValidationError(
                "Windows service binary size changed during verification"
            )

        actual = digest.hexdigest()
        result = WindowsScmBinaryVerification(
            binary_path=manifest.binary_path,
            expected_sha256=manifest.binary_sha256,
            actual_sha256=actual,
            size_bytes=size,
            modified_time_ns=after.st_mtime_ns,
        )
        if not result.matched:
            raise AuthorityValidationError(
                "Windows service binary SHA-256 mismatch"
            )
        return result


class WindowsScmServiceRegistrationAdmission:
    """Compose manifest-policy admission with actual binary verification."""

    def __init__(
        self,
        *,
        policy: WindowsScmServiceRegistrationPolicy,
        binary_verifier: Optional[WindowsScmBinaryVerifier] = None,
    ) -> None:
        if not isinstance(
            policy,
            WindowsScmServiceRegistrationPolicy,
        ):
            raise AuthorityValidationError(
                "policy must be WindowsScmServiceRegistrationPolicy"
            )
        if (
            binary_verifier is not None
            and not isinstance(binary_verifier, WindowsScmBinaryVerifier)
        ):
            raise AuthorityValidationError(
                "binary_verifier must be WindowsScmBinaryVerifier or None"
            )
        self.policy = policy
        self.binary_verifier = binary_verifier or WindowsScmBinaryVerifier()

    def assert_admitted(
        self,
        manifest: WindowsScmServiceRegistrationManifest,
    ) -> WindowsScmRegistrationAdmissionResult:
        manifest_sha256 = self.policy.assert_admitted(manifest)
        binary = self.binary_verifier.verify(manifest)
        return WindowsScmRegistrationAdmissionResult(
            manifest_sha256=manifest_sha256,
            binary=binary,
        )
