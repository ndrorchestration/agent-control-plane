"""Non-mutating Windows SCM registration call-plan compiler."""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_registration import (
    WindowsScmServiceRegistrationManifest,
    WindowsScmServiceRegistrationPolicy,
    WindowsScmServiceStartType,
)


SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_ERROR_NORMAL = 0x00000001
SC_MANAGER_CONNECT = 0x0001
SC_MANAGER_CREATE_SERVICE = 0x0002
SERVICE_QUERY_STATUS = 0x0004
SERVICE_START = 0x0010
SERVICE_STOP = 0x0020
SERVICE_CHANGE_CONFIG = 0x0002

_REQUIRED_REGISTRATION_EXPORTS = (
    "OpenSCManagerW",
    "CreateServiceW",
    "ChangeServiceConfig2W",
    "CloseServiceHandle",
)

_PASSWORDLESS_ACCOUNTS = {
    "localsystem",
    r"nt authority\system",
    r"nt authority\localservice",
    r"nt authority\networkservice",
    "localservice",
    "networkservice",
}


def _account_requires_secret(account_name: str) -> bool:
    normalized = account_name.strip().lower()
    if normalized in _PASSWORDLESS_ACCOUNTS:
        return False
    if normalized.startswith(r"nt service\"):
        return False
    return True


def _quote_binary_path(path: str) -> str:
    if '"' in path:
        raise AuthorityValidationError(
            "Windows service binary path must not contain quotes"
        )
    return f'"{path}"'


def _dependencies_multi_sz(dependencies: tuple[str, ...]) -> Optional[str]:
    if not dependencies:
        return None
    return "\0".join(dependencies) + "\0\0"


@dataclass(frozen=True)
class WindowsScmServiceRegistrationPlan:
    manifest_sha256: str
    service_name: str
    display_name: str
    binary_path_command: str
    service_type: int
    start_type: int
    error_control: int
    dependencies_multi_sz: Optional[str]
    account_name: str
    credential_reference: Optional[str]
    requires_credential_resolution: bool
    delayed_auto_start: bool
    desired_scm_access: int
    desired_service_access: int


@dataclass(frozen=True)
class WindowsScmRegistrationNativeApiProbe:
    is_windows: bool
    required_exports: tuple[str, ...]
    available_exports: tuple[str, ...]

    @property
    def available(self) -> bool:
        return (
            self.is_windows
            and self.available_exports == self.required_exports
        )


class WindowsScmServiceRegistrationPlanner:
    """Compile admitted registration intent into exact non-mutating call data."""

    def __init__(
        self,
        *,
        policy: WindowsScmServiceRegistrationPolicy,
    ) -> None:
        if not isinstance(
            policy,
            WindowsScmServiceRegistrationPolicy,
        ):
            raise AuthorityValidationError(
                "policy must be WindowsScmServiceRegistrationPolicy"
            )
        self.policy = policy

    def compile(
        self,
        manifest: WindowsScmServiceRegistrationManifest,
    ) -> WindowsScmServiceRegistrationPlan:
        manifest_sha256 = self.policy.assert_admitted(manifest)
        needs_secret = _account_requires_secret(manifest.account_name)
        if needs_secret and manifest.credential_reference is None:
            raise AuthorityValidationError(
                "credential_reference required for admitted service account"
            )

        desired_service_access = (
            SERVICE_QUERY_STATUS
            | SERVICE_START
            | SERVICE_STOP
            | SERVICE_CHANGE_CONFIG
        )
        return WindowsScmServiceRegistrationPlan(
            manifest_sha256=manifest_sha256,
            service_name=manifest.service_name,
            display_name=manifest.display_name,
            binary_path_command=_quote_binary_path(manifest.binary_path),
            service_type=SERVICE_WIN32_OWN_PROCESS,
            start_type=int(manifest.start_type),
            error_control=SERVICE_ERROR_NORMAL,
            dependencies_multi_sz=_dependencies_multi_sz(
                manifest.dependencies
            ),
            account_name=manifest.account_name,
            credential_reference=manifest.credential_reference,
            requires_credential_resolution=needs_secret,
            delayed_auto_start=manifest.delayed_auto_start,
            desired_scm_access=(
                SC_MANAGER_CONNECT | SC_MANAGER_CREATE_SERVICE
            ),
            desired_service_access=desired_service_access,
        )


def probe_windows_scm_registration_api() -> WindowsScmRegistrationNativeApiProbe:
    if os.name != "nt":
        return WindowsScmRegistrationNativeApiProbe(
            is_windows=False,
            required_exports=_REQUIRED_REGISTRATION_EXPORTS,
            available_exports=(),
        )
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    available = tuple(
        name
        for name in _REQUIRED_REGISTRATION_EXPORTS
        if hasattr(advapi32, name)
    )
    return WindowsScmRegistrationNativeApiProbe(
        is_windows=True,
        required_exports=_REQUIRED_REGISTRATION_EXPORTS,
        available_exports=available,
    )
