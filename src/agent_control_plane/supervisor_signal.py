"""OS signal latch for bounded ACP supervisor-service integration."""

from __future__ import annotations

from dataclasses import dataclass
import signal
from types import FrameType
from typing import Optional

from .authority import AuthorityValidationError


@dataclass(frozen=True)
class SupervisorSignalSnapshot:
    signal_name: Optional[str]


class SupervisorSignalLatch:
    """Latch the first supported OS stop signal and preserve it idempotently."""

    def __init__(self) -> None:
        self._signal_name: Optional[str] = None
        self._previous: dict[int, object] = {}
        self._installed = False

    def snapshot(self) -> SupervisorSignalSnapshot:
        return SupervisorSignalSnapshot(signal_name=self._signal_name)

    def signal_name(self) -> Optional[str]:
        return self._signal_name

    def _handler(
        self,
        signum: int,
        frame: Optional[FrameType],
    ) -> None:
        if self._signal_name is not None:
            return
        if signum == signal.SIGTERM:
            self._signal_name = "SIGTERM"
        elif signum == signal.SIGINT:
            self._signal_name = "SIGINT"
        else:
            raise AuthorityValidationError(
                f"unsupported supervisor signal number: {signum}"
            )

    def install(self) -> None:
        if self._installed:
            return
        for signum in (signal.SIGTERM, signal.SIGINT):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handler)
        self._installed = True

    def restore(self) -> None:
        if not self._installed:
            return
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)
        self._previous.clear()
        self._installed = False

    def __enter__(self) -> "SupervisorSignalLatch":
        self.install()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.restore()
