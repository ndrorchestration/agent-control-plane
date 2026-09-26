"""Windows SCM service-host contract over ACP service-host semantics.

This module models the ServiceMain/HandlerEx-facing state machine without
registering or installing a Windows service. Native hosting adapters may call
these methods from their SCM callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag
from typing import Optional

from .authority import AuthorityValidationError
from .supervisor_service import SupervisorStopReason
from .supervisor_service_host import SupervisorServiceHostEventLatch
from .windows_scm_adapter import (
    WindowsScmControlAdapter,
    WindowsScmControlDisposition,
    WindowsScmControlResult,
)


class WindowsScmServiceState(IntEnum):
    STOPPED = 0x00000001
    START_PENDING = 0x00000002
    STOP_PENDING = 0x00000003
    RUNNING = 0x00000004


class WindowsScmAcceptedControl(IntFlag):
    NONE = 0
    STOP = 0x00000001
    SHUTDOWN = 0x00000004
    PRESHUTDOWN = 0x00000100


@dataclass(frozen=True)
class WindowsScmServiceStatus:
    state: WindowsScmServiceState
    accepted_controls: WindowsScmAcceptedControl
    win32_exit_code: int = 0
    service_specific_exit_code: int = 0
    checkpoint: int = 0
    wait_hint_ms: int = 0


class WindowsScmServiceHostContract:
    """State/status bridge intended for ServiceMain + HandlerEx callbacks."""

    def __init__(
        self,
        *,
        control_adapter: Optional[WindowsScmControlAdapter] = None,
        event_latch: Optional[SupervisorServiceHostEventLatch] = None,
    ) -> None:
        self.control_adapter = control_adapter or WindowsScmControlAdapter()
        self.event_latch = event_latch or SupervisorServiceHostEventLatch()
        self._status = WindowsScmServiceStatus(
            state=WindowsScmServiceState.STOPPED,
            accepted_controls=WindowsScmAcceptedControl.NONE,
        )

    def status(self) -> WindowsScmServiceStatus:
        return self._status

    def service_main_enter(
        self,
        *,
        checkpoint: int = 1,
        wait_hint_ms: int = 5000,
    ) -> WindowsScmServiceStatus:
        if self._status.state is not WindowsScmServiceState.STOPPED:
            raise AuthorityValidationError(
                "ServiceMain startup requires STOPPED state"
            )
        if checkpoint < 1:
            raise AuthorityValidationError(
                "startup checkpoint must be >= 1"
            )
        if wait_hint_ms < 0:
            raise AuthorityValidationError(
                "wait_hint_ms must be >= 0"
            )
        self._status = WindowsScmServiceStatus(
            state=WindowsScmServiceState.START_PENDING,
            accepted_controls=WindowsScmAcceptedControl.NONE,
            checkpoint=checkpoint,
            wait_hint_ms=wait_hint_ms,
        )
        return self._status

    def mark_running(self) -> WindowsScmServiceStatus:
        if self._status.state is not WindowsScmServiceState.START_PENDING:
            raise AuthorityValidationError(
                "RUNNING requires START_PENDING state"
            )
        self._status = WindowsScmServiceStatus(
            state=WindowsScmServiceState.RUNNING,
            accepted_controls=(
                WindowsScmAcceptedControl.STOP
                | WindowsScmAcceptedControl.SHUTDOWN
                | WindowsScmAcceptedControl.PRESHUTDOWN
            ),
        )
        return self._status

    def handler_ex(self, control_code: int) -> WindowsScmControlResult:
        if self._status.state not in (
            WindowsScmServiceState.RUNNING,
            WindowsScmServiceState.STOP_PENDING,
        ):
            raise AuthorityValidationError(
                "SCM control received outside running service state"
            )

        result = self.control_adapter.translate(control_code)
        if result.disposition is WindowsScmControlDisposition.STATUS_ONLY:
            return result

        assert result.host_event is not None
        self.event_latch.request(result.host_event)
        if self._status.state is WindowsScmServiceState.RUNNING:
            self._status = WindowsScmServiceStatus(
                state=WindowsScmServiceState.STOP_PENDING,
                accepted_controls=WindowsScmAcceptedControl.NONE,
                checkpoint=1,
                wait_hint_ms=5000,
            )
        return result

    def stop_reason(self) -> Optional[SupervisorStopReason]:
        return self.event_latch.stop_reason()

    def stop_reason_provider(
        self,
        cycle_index: int,
    ) -> Optional[SupervisorStopReason]:
        # cycle_index is accepted to match BoundedSupervisorServiceRunner's
        # provider shape. Windows host semantics are independent of cycle count.
        if (
            isinstance(cycle_index, bool)
            or not isinstance(cycle_index, int)
            or cycle_index < 0
        ):
            raise AuthorityValidationError(
                "cycle_index must be an integer >= 0"
            )
        return self.stop_reason()

    def update_stop_pending(
        self,
        *,
        checkpoint: int,
        wait_hint_ms: int,
    ) -> WindowsScmServiceStatus:
        if self._status.state is not WindowsScmServiceState.STOP_PENDING:
            raise AuthorityValidationError(
                "stop-pending update requires STOP_PENDING state"
            )
        if checkpoint < 1:
            raise AuthorityValidationError(
                "stop checkpoint must be >= 1"
            )
        if wait_hint_ms < 0:
            raise AuthorityValidationError(
                "wait_hint_ms must be >= 0"
            )
        self._status = WindowsScmServiceStatus(
            state=WindowsScmServiceState.STOP_PENDING,
            accepted_controls=WindowsScmAcceptedControl.NONE,
            checkpoint=checkpoint,
            wait_hint_ms=wait_hint_ms,
        )
        return self._status

    def mark_stopped(
        self,
        *,
        win32_exit_code: int = 0,
        service_specific_exit_code: int = 0,
    ) -> WindowsScmServiceStatus:
        if self._status.state not in (
            WindowsScmServiceState.START_PENDING,
            WindowsScmServiceState.RUNNING,
            WindowsScmServiceState.STOP_PENDING,
        ):
            raise AuthorityValidationError(
                "STOPPED requires an active service state"
            )
        if win32_exit_code < 0 or service_specific_exit_code < 0:
            raise AuthorityValidationError(
                "service exit codes must be >= 0"
            )
        self._status = WindowsScmServiceStatus(
            state=WindowsScmServiceState.STOPPED,
            accepted_controls=WindowsScmAcceptedControl.NONE,
            win32_exit_code=win32_exit_code,
            service_specific_exit_code=service_specific_exit_code,
        )
        return self._status
