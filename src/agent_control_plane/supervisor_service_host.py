"""Platform-neutral service-host event adapter for ACP supervisor lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .authority import AuthorityValidationError
from .supervisor_service import SupervisorStopReason


class SupervisorServiceHostEvent(str, Enum):
    STOP = "stop"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class SupervisorServiceHostSnapshot:
    event: Optional[SupervisorServiceHostEvent]
    stop_reason: Optional[SupervisorStopReason]


class SupervisorServiceHostEventLatch:
    """Latch the first supported host event and expose its ACP stop reason."""

    def __init__(self) -> None:
        self._event: Optional[SupervisorServiceHostEvent] = None

    def request(
        self,
        event: SupervisorServiceHostEvent,
    ) -> SupervisorServiceHostSnapshot:
        if not isinstance(event, SupervisorServiceHostEvent):
            raise AuthorityValidationError(
                "event must be SupervisorServiceHostEvent"
            )
        if self._event is None:
            self._event = event
        return self.snapshot()

    def snapshot(self) -> SupervisorServiceHostSnapshot:
        return SupervisorServiceHostSnapshot(
            event=self._event,
            stop_reason=self.stop_reason(),
        )

    def stop_reason(self) -> Optional[SupervisorStopReason]:
        if self._event is SupervisorServiceHostEvent.STOP:
            return SupervisorStopReason.SERVICE_STOP
        if self._event is SupervisorServiceHostEvent.SHUTDOWN:
            return SupervisorStopReason.SERVICE_SHUTDOWN
        return None
