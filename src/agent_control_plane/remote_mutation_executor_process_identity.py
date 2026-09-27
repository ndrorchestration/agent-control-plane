"""Read-only executor process-identity preflight.

This module does not authorize execution. It records locally observed process
facts and compares them with an explicit policy so accidental execution under
the wrong interpreter/user can fail closed before a live executor is invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from typing import Iterable

EXECUTOR_PROCESS_IDENTITY_SCHEMA_VERSION = (
    "agent-control-plane.executor-process-identity.v0-candidate"
)
EXECUTOR_PROCESS_EVIDENCE_LEVEL = "SELF_REPORTED_LOCAL"


class ExecutorProcessIdentityError(ValueError):
    pass


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutorProcessIdentityError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ExecutorProcessIdentityError(f"{field} must be lowercase sha256")
    return value


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_path(value: str | Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        raise ExecutorProcessIdentityError("executable path must be absolute")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ExecutorProcessIdentityError("executable path must be an existing file")
    return os.path.normcase(str(resolved))


@dataclass(frozen=True)
class ExecutorProcessPolicy:
    policy_id: str
    executor_id: str
    allowed_executable_paths: tuple[str, ...]
    allowed_executable_sha256: tuple[str, ...]
    allowed_usernames: tuple[str, ...]
    schema_version: str = EXECUTOR_PROCESS_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _required(self.policy_id, "policy_id"))
        object.__setattr__(self, "executor_id", _required(self.executor_id, "executor_id"))
        if self.schema_version != EXECUTOR_PROCESS_IDENTITY_SCHEMA_VERSION:
            raise ExecutorProcessIdentityError(
                f"unsupported schema_version: {self.schema_version}"
            )

        paths = tuple(_canonical_path(item) for item in self.allowed_executable_paths)
        hashes = tuple(_sha256(item, "allowed_executable_sha256") for item in self.allowed_executable_sha256)
        users = tuple(_required(item, "allowed_username") for item in self.allowed_usernames)
        if not paths or not hashes or not users:
            raise ExecutorProcessIdentityError(
                "process policy requires at least one path, hash, and username"
            )
        object.__setattr__(self, "allowed_executable_paths", tuple(dict.fromkeys(paths)))
        object.__setattr__(self, "allowed_executable_sha256", tuple(dict.fromkeys(hashes)))
        object.__setattr__(self, "allowed_usernames", tuple(dict.fromkeys(users)))


@dataclass(frozen=True)
class ExecutorProcessIdentityRecord:
    policy_id: str
    executor_id: str
    executable_path: str
    executable_sha256: str
    username: str
    pid: int
    platform_system: str
    executable_path_allowed: bool
    executable_hash_allowed: bool
    username_allowed: bool
    policy_satisfied: bool
    evidence_level: str = EXECUTOR_PROCESS_EVIDENCE_LEVEL
    execution_authorized: bool = False
    mutation_executed: bool = False
    schema_version: str = EXECUTOR_PROCESS_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "policy_id",
            "executor_id",
            "executable_path",
            "username",
            "platform_system",
            "evidence_level",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        _sha256(self.executable_sha256, "executable_sha256")
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise ExecutorProcessIdentityError("pid must be a positive integer")
        if self.evidence_level != EXECUTOR_PROCESS_EVIDENCE_LEVEL:
            raise ExecutorProcessIdentityError(
                "executor process identity evidence level must remain SELF_REPORTED_LOCAL"
            )
        if self.execution_authorized is not False or self.mutation_executed is not False:
            raise ExecutorProcessIdentityError(
                "process identity preflight cannot authorize or claim mutation execution"
            )
        expected = (
            self.executable_path_allowed
            and self.executable_hash_allowed
            and self.username_allowed
        )
        if self.policy_satisfied is not expected:
            raise ExecutorProcessIdentityError(
                "policy_satisfied must equal the conjunction of policy checks"
            )

    def canonical_bytes(self) -> bytes:
        payload = {
            "evidence_level": self.evidence_level,
            "executable_path": self.executable_path,
            "executable_sha256": self.executable_sha256,
            "executor_id": self.executor_id,
            "pid": self.pid,
            "platform_system": self.platform_system,
            "policy_id": self.policy_id,
            "policy_satisfied": self.policy_satisfied,
            "username": self.username,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def evidence_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def build_executor_process_policy(
    *,
    policy_id: str,
    executor_id: str,
    executable_paths: Iterable[str | Path],
    executable_sha256: Iterable[str],
    usernames: Iterable[str],
) -> ExecutorProcessPolicy:
    return ExecutorProcessPolicy(
        policy_id=policy_id,
        executor_id=executor_id,
        allowed_executable_paths=tuple(str(item) for item in executable_paths),
        allowed_executable_sha256=tuple(executable_sha256),
        allowed_usernames=tuple(usernames),
    )


def inspect_executor_process_identity(
    policy: ExecutorProcessPolicy,
    *,
    executor_id: str,
    executable_path: str | Path | None = None,
    username: str | None = None,
    pid: int | None = None,
    platform_system: str | None = None,
) -> ExecutorProcessIdentityRecord:
    """Observe local process facts and compare them with an explicit policy."""
    if not isinstance(policy, ExecutorProcessPolicy):
        raise TypeError("policy must be ExecutorProcessPolicy")

    executor = _required(executor_id, "executor_id")
    observed_path = _canonical_path(executable_path or sys.executable)
    observed_hash = _hash_file(Path(observed_path))
    observed_user = _required(username or getpass.getuser(), "username")
    observed_pid = os.getpid() if pid is None else pid
    observed_platform = _required(
        platform_system or platform.system(),
        "platform_system",
    )

    path_ok = observed_path in policy.allowed_executable_paths
    hash_ok = observed_hash in policy.allowed_executable_sha256
    user_ok = observed_user in policy.allowed_usernames
    executor_ok = executor == policy.executor_id

    return ExecutorProcessIdentityRecord(
        policy_id=policy.policy_id,
        executor_id=executor,
        executable_path=observed_path,
        executable_sha256=observed_hash,
        username=observed_user,
        pid=observed_pid,
        platform_system=observed_platform,
        executable_path_allowed=path_ok and executor_ok,
        executable_hash_allowed=hash_ok and executor_ok,
        username_allowed=user_ok and executor_ok,
        policy_satisfied=executor_ok and path_ok and hash_ok and user_ok,
    )
