"""Deterministic caller-driven supervision cycle for ACP relay resilience."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .authority import AuthorityValidationError
from .relay_dead_letter import DurableRelayDeadLetterStore, dead_letter_exhausted
from .relay_forward_queue import DurableRelayForwardQueue
from .relay_retry_policy import (
    BoundedRelayRetryPolicy,
    RelayRetryDisposition,
    RelayRetryResult,
    RetryingRelayForwarder,
)


class RelaySupervisorHealth(str, Enum):
    IDLE = "idle"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RelaySupervisorCycleReport:
    health: RelaySupervisorHealth
    retry_results: tuple[RelayRetryResult, ...]
    dead_lettered_item_ids: tuple[str, ...]
    pending_count: int
    pending_bytes: int
    dead_letter_count: int


class RelaySupervisorCycle:
    """Run one deterministic retry/dead-letter maintenance cycle.

    This class deliberately does not schedule itself, sleep, restart processes,
    or create background workers. A caller decides when each cycle runs.
    """

    def __init__(
        self,
        *,
        queue: DurableRelayForwardQueue,
        dead_letter_store: DurableRelayDeadLetterStore,
        retry_policy: BoundedRelayRetryPolicy,
        exchange_for: Callable[[str], Callable[[bytes], bytes]],
    ) -> None:
        if not isinstance(queue, DurableRelayForwardQueue):
            raise AuthorityValidationError(
                "queue must be DurableRelayForwardQueue"
            )
        if not isinstance(dead_letter_store, DurableRelayDeadLetterStore):
            raise AuthorityValidationError(
                "dead_letter_store must be DurableRelayDeadLetterStore"
            )
        if not isinstance(retry_policy, BoundedRelayRetryPolicy):
            raise AuthorityValidationError(
                "retry_policy must be BoundedRelayRetryPolicy"
            )
        if not callable(exchange_for):
            raise AuthorityValidationError(
                "exchange_for must be callable"
            )
        self.queue = queue
        self.dead_letter_store = dead_letter_store
        self.retry_policy = retry_policy
        self.forwarder = RetryingRelayForwarder(
            queue=queue,
            policy=retry_policy,
            exchange_for=exchange_for,
        )

    def run(
        self,
        *,
        now: str,
        dead_letter_reason: str = "retry attempts exhausted",
    ) -> RelaySupervisorCycleReport:
        retry_results = self.forwarder.sweep(now=now)

        dead_lettered = dead_letter_exhausted(
            queue=self.queue,
            store=self.dead_letter_store,
            policy=self.retry_policy,
            reason=dead_letter_reason,
            dead_lettered_at=now,
        )

        usage = self.queue.usage()
        dead_letter_count = len(self.dead_letter_store.all())

        dispositions = {result.disposition for result in retry_results}
        if dead_lettered or RelayRetryDisposition.EXHAUSTED in dispositions:
            health = RelaySupervisorHealth.BLOCKED
        elif (
            RelayRetryDisposition.FAILED in dispositions
            or RelayRetryDisposition.DEFERRED in dispositions
            or int(usage["pending_items"]) > 0
        ):
            health = RelaySupervisorHealth.DEGRADED
        elif retry_results:
            health = RelaySupervisorHealth.HEALTHY
        else:
            health = RelaySupervisorHealth.IDLE

        return RelaySupervisorCycleReport(
            health=health,
            retry_results=retry_results,
            dead_lettered_item_ids=dead_lettered,
            pending_count=int(usage["pending_items"]),
            pending_bytes=int(usage["pending_bytes"]),
            dead_letter_count=dead_letter_count,
        )
