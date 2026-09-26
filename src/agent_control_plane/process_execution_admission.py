"""Fail-closed execution admission for ACP-managed subprocess specifications."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Optional

from .authority import AuthorityValidationError
from .process_runtime import (
    ManagedProcessController,
    ManagedProcessSpec,
    ProcessObservation,
)


PROCESS_EXECUTION_ADMISSION_SCHEMA_VERSION = (
    "agent-control-plane.process-execution-admission.v0-candidate"
)


def _canonical_path(value: str) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def managed_process_spec_sha256(spec: ManagedProcessSpec) -> str:
    if not isinstance(spec, ManagedProcessSpec):
        raise AuthorityValidationError("spec must be ManagedProcessSpec")
    payload = {
        "process_id": spec.process_id,
        "argv": list(spec.argv),
        "cwd": (
            None
            if spec.cwd is None
            else _canonical_path(spec.cwd)
        ),
        "env": (
            None
            if spec.env is None
            else {
                key: spec.env[key]
                for key in sorted(spec.env)
            }
        ),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProcessExecutionAdmissionPolicy:
    allowed_executables: tuple[str, ...]
    allowed_cwd_roots: tuple[str, ...] = ()
    allowed_environment_keys: tuple[str, ...] = ()
    forbidden_environment_keys: tuple[str, ...] = ()
    allowed_spec_sha256: tuple[str, ...] = ()
    allow_inherited_environment: bool = False
    allow_inherited_cwd: bool = False
    required_effective_uid: Optional[int] = None
    schema_version: str = PROCESS_EXECUTION_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.allowed_executables, tuple)
            or not self.allowed_executables
        ):
            raise AuthorityValidationError(
                "allowed_executables must be a non-empty tuple"
            )
        object.__setattr__(
            self,
            "allowed_executables",
            tuple(_canonical_path(value) for value in self.allowed_executables),
        )
        object.__setattr__(
            self,
            "allowed_cwd_roots",
            tuple(_canonical_path(value) for value in self.allowed_cwd_roots),
        )
        for values, field_name in (
            (self.allowed_environment_keys, "allowed_environment_keys"),
            (self.forbidden_environment_keys, "forbidden_environment_keys"),
            (self.allowed_spec_sha256, "allowed_spec_sha256"),
        ):
            if not isinstance(values, tuple):
                raise AuthorityValidationError(
                    f"{field_name} must be a tuple"
                )
            if len(set(values)) != len(values):
                raise AuthorityValidationError(
                    f"{field_name} must not contain duplicates"
                )
        if not isinstance(self.allow_inherited_environment, bool):
            raise AuthorityValidationError(
                "allow_inherited_environment must be bool"
            )
        if not isinstance(self.allow_inherited_cwd, bool):
            raise AuthorityValidationError(
                "allow_inherited_cwd must be bool"
            )
        if self.required_effective_uid is not None:
            if (
                isinstance(self.required_effective_uid, bool)
                or not isinstance(self.required_effective_uid, int)
                or self.required_effective_uid < 0
            ):
                raise AuthorityValidationError(
                    "required_effective_uid must be an integer >= 0 or None"
                )
        if self.schema_version != PROCESS_EXECUTION_ADMISSION_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def _cwd_allowed(self, cwd: str) -> bool:
        candidate = Path(_canonical_path(cwd))
        for root in self.allowed_cwd_roots:
            root_path = Path(root)
            try:
                candidate.relative_to(root_path)
                return True
            except ValueError:
                continue
        return False

    def assert_admitted(
        self,
        spec: ManagedProcessSpec,
        *,
        effective_uid: Optional[int] = None,
    ) -> str:
        if not isinstance(spec, ManagedProcessSpec):
            raise AuthorityValidationError(
                "spec must be ManagedProcessSpec"
            )

        executable = _canonical_path(spec.argv[0])
        if executable not in self.allowed_executables:
            raise AuthorityValidationError(
                "managed process executable not admitted"
            )

        if spec.cwd is None:
            if not self.allow_inherited_cwd:
                raise AuthorityValidationError(
                    "managed process inherited cwd not admitted"
                )
        else:
            if not self.allowed_cwd_roots:
                raise AuthorityValidationError(
                    "managed process cwd roots not configured"
                )
            if not self._cwd_allowed(spec.cwd):
                raise AuthorityValidationError(
                    "managed process cwd not admitted"
                )

        if spec.env is None:
            if not self.allow_inherited_environment:
                raise AuthorityValidationError(
                    "managed process inherited environment not admitted"
                )
        else:
            keys = set(spec.env)
            forbidden = keys.intersection(self.forbidden_environment_keys)
            if forbidden:
                raise AuthorityValidationError(
                    "managed process environment contains forbidden key"
                )
            unexpected = keys.difference(self.allowed_environment_keys)
            if unexpected:
                raise AuthorityValidationError(
                    "managed process environment key not admitted"
                )

        digest = managed_process_spec_sha256(spec)
        if self.allowed_spec_sha256 and digest not in self.allowed_spec_sha256:
            raise AuthorityValidationError(
                "managed process specification fingerprint not admitted"
            )

        if self.required_effective_uid is not None:
            if effective_uid is None:
                raise AuthorityValidationError(
                    "effective uid unavailable for required privilege binding"
                )
            if effective_uid != self.required_effective_uid:
                raise AuthorityValidationError(
                    "managed process effective uid not admitted"
                )

        return digest


class AdmittedManagedProcessController(ManagedProcessController):
    """Managed process controller that enforces execution admission before spawn."""

    def __init__(
        self,
        spec: ManagedProcessSpec,
        *,
        admission_policy: ProcessExecutionAdmissionPolicy,
    ) -> None:
        if not isinstance(
            admission_policy,
            ProcessExecutionAdmissionPolicy,
        ):
            raise AuthorityValidationError(
                "admission_policy must be ProcessExecutionAdmissionPolicy"
            )
        super().__init__(spec)
        self.admission_policy = admission_policy

    def _effective_uid(self) -> Optional[int]:
        getuid = getattr(os, "geteuid", None)
        if getuid is None:
            return None
        return int(getuid())

    def start(self) -> ProcessObservation:
        self.admission_policy.assert_admitted(
            self.spec,
            effective_uid=self._effective_uid(),
        )
        return super().start()
