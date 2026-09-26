"""Explicit bounded worker-concurrency contract for ACP supervision."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from .authority import AuthorityValidationError


class SupervisorWorkerSchedulingMode(str, Enum):
    CONTRACT_ORDER_SERIAL = "contract_order_serial"


T = TypeVar("T")


@dataclass(frozen=True)
class SupervisorConcurrencyPolicy:
    """Current accepted worker scheduling semantics: deterministic serial only."""

    max_in_flight_workers: int = 1
    scheduling_mode: SupervisorWorkerSchedulingMode = (
        SupervisorWorkerSchedulingMode.CONTRACT_ORDER_SERIAL
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_in_flight_workers, bool)
            or not isinstance(self.max_in_flight_workers, int)
            or self.max_in_flight_workers < 1
        ):
            raise AuthorityValidationError(
                "max_in_flight_workers must be an integer >= 1"
            )
        if not isinstance(
            self.scheduling_mode,
            SupervisorWorkerSchedulingMode,
        ):
            raise AuthorityValidationError(
                "scheduling_mode must be SupervisorWorkerSchedulingMode"
            )
        if self.max_in_flight_workers != 1:
            raise AuthorityValidationError(
                "parallel supervisor worker scheduling is not authorized"
            )
        if (
            self.scheduling_mode
            is not SupervisorWorkerSchedulingMode.CONTRACT_ORDER_SERIAL
        ):
            raise AuthorityValidationError(
                "unsupported supervisor worker scheduling mode"
            )

    def ordered(self, workers: tuple[T, ...]) -> tuple[T, ...]:
        if not isinstance(workers, tuple):
            raise AuthorityValidationError("workers must be a tuple")
        return workers
