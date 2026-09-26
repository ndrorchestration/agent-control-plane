"""Pure Windows SCM control-code translation into ACP service-host events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .authority import AuthorityValidationError
from .supervisor_service_host import SupervisorServiceHostEvent


class WindowsScmControlCode(int, Enum):
    STOP = 0x00000001
    PAUSE = 0x00000002
    CONTINUE = 0x00000003
    INTERROGATE = 0x00000004
    SHUTDOWN = 0x00000005
    PRESHUTDOWN = 0x0000000F


class WindowsScmControlDisposition(str, Enum):
    HOST_EVENT = "host_event"
    STATUS_ONLY = "status_only"


@dataclass(frozen=True)
class WindowsScmControlResult:
    disposition: WindowsScmControlDisposition
    host_event: SupervisorServiceHostEvent | None = None


class WindowsScmControlAdapter:
    """Translate supported Windows SCM controls without owning service hosting."""

    def translate(self, control_code: int) -> WindowsScmControlResult:
        try:
            code = WindowsScmControlCode(control_code)
        except (TypeError, ValueError) as exc:
            raise AuthorityValidationError(
                f"unsupported Windows SCM control code: {control_code}"
            ) from exc

        if code is WindowsScmControlCode.STOP:
            return WindowsScmControlResult(
                disposition=WindowsScmControlDisposition.HOST_EVENT,
                host_event=SupervisorServiceHostEvent.STOP,
            )
        if code is WindowsScmControlCode.SHUTDOWN:
            return WindowsScmControlResult(
                disposition=WindowsScmControlDisposition.HOST_EVENT,
                host_event=SupervisorServiceHostEvent.SHUTDOWN,
            )
        if code is WindowsScmControlCode.PRESHUTDOWN:
            return WindowsScmControlResult(
                disposition=WindowsScmControlDisposition.HOST_EVENT,
                host_event=SupervisorServiceHostEvent.PRESHUTDOWN,
            )
        if code is WindowsScmControlCode.INTERROGATE:
            return WindowsScmControlResult(
                disposition=WindowsScmControlDisposition.STATUS_ONLY,
            )

        # ACP has no pause/resume lifecycle state today. Do not silently
        # reinterpret those controls as stop/start operations.
        raise AuthorityValidationError(
            f"Windows SCM control not admitted by ACP lifecycle: {code.name}"
        )
