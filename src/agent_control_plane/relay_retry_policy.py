"""Deterministic bounded retry policy for durable ACP relay forwards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Mapping

from .authority import AuthorityValidationError
from .relay_forward_queue import DurableRelayForwardQueue, PendingRelayForward


def _utc(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AuthorityValidationError(
            f"{field_name} must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(
            f"{field_name} must be timezone-aware UTC"
        )
    if parsed.utcoffset() != timedelta(0):
        raise AuthorityValidationError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc)


class RelayRetryDisposition(str, Enum):
    DELIVERED = "delivered"
    DEFERRED = "deferred"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class RelayRetryResult:
    item_id: str
    disposition: RelayRetryDisposition
    attempt_count: int
    next_attempt_at: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BoundedRelayRetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 60.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise AuthorityValidationError(
                "max_attempts must be an integer >= 1"
            )
        for value, field_name in (
            (self.base_delay_seconds, "base_delay_seconds"),
            (self.multiplier, "multiplier"),
            (self.max_delay_seconds, "max_delay_seconds"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise AuthorityValidationError(
                    f"{field_name} must be > 0"
                )
        if self.multiplier < 1:
            raise AuthorityValidationError(
                "multiplier must be >= 1"
            )
        if self.max_delay_seconds < self.base_delay_seconds:
            raise AuthorityValidationError(
                "max_delay_seconds must be >= base_delay_seconds"
            )

    def delay_after_attempt(self, attempt_count: int) -> float:
        if (
            isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
            or attempt_count < 1
        ):
            raise AuthorityValidationError(
                "attempt_count must be an integer >= 1"
            )
        delay = self.base_delay_seconds * (
            self.multiplier ** (attempt_count - 1)
        )
        return min(float(delay), float(self.max_delay_seconds))

    def next_attempt_at(
        self,
        item: PendingRelayForward,
    ) -> str | None:
        if item.attempt_count == 0 or item.last_attempt_at is None:
            return None
        when = _utc(item.last_attempt_at, "last_attempt_at") + timedelta(
            seconds=self.delay_after_attempt(item.attempt_count)
        )
        return when.isoformat().replace("+00:00", "Z")

    def is_exhausted(self, item: PendingRelayForward) -> bool:
        return item.attempt_count >= self.max_attempts

    def is_due(
        self,
        item: PendingRelayForward,
        *,
        now: str,
    ) -> bool:
        if self.is_exhausted(item):
            return False
        next_attempt = self.next_attempt_at(item)
        if next_attempt is None:
            return True
        return _utc(now, "now") >= _utc(
            next_attempt,
            "next_attempt_at",
        )


class RetryingRelayForwarder:
    """Perform one deterministic retry sweep over a durable forward queue."""

    def __init__(
        self,
        *,
        queue: DurableRelayForwardQueue,
        policy: BoundedRelayRetryPolicy,
        exchange_for: Callable[[str], Callable[[bytes], bytes]],
    ) -> None:
        if not isinstance(queue, DurableRelayForwardQueue):
            raise AuthorityValidationError(
                "queue must be DurableRelayForwardQueue"
            )
        if not isinstance(policy, BoundedRelayRetryPolicy):
            raise AuthorityValidationError(
                "policy must be BoundedRelayRetryPolicy"
            )
        if not callable(exchange_for):
            raise AuthorityValidationError(
                "exchange_for must be callable"
            )
        self.queue = queue
        self.policy = policy
        self.exchange_for = exchange_for

    def sweep(
        self,
        *,
        now: str,
    ) -> tuple[RelayRetryResult, ...]:
        _utc(now, "now")
        results: list[RelayRetryResult] = []

        for item in self.queue.pending():
            if self.policy.is_exhausted(item):
                results.append(
                    RelayRetryResult(
                        item_id=item.item_id,
                        disposition=RelayRetryDisposition.EXHAUSTED,
                        attempt_count=item.attempt_count,
                    )
                )
                continue

            if not self.policy.is_due(item, now=now):
                results.append(
                    RelayRetryResult(
                        item_id=item.item_id,
                        disposition=RelayRetryDisposition.DEFERRED,
                        attempt_count=item.attempt_count,
                        next_attempt_at=self.policy.next_attempt_at(item),
                    )
                )
                continue

            exchange = self.exchange_for(item.downstream_id)
            if not callable(exchange):
                raise AuthorityValidationError(
                    "exchange_for must return a callable"
                )

            attempted = self.queue.mark_attempt(
                item.item_id,
                attempted_at=now,
            )
            try:
                response = exchange(attempted.payload)
                if not isinstance(response, bytes):
                    raise AuthorityValidationError(
                        "relay downstream exchange must return bytes"
                    )
            except Exception as exc:
                refreshed = self.queue.get(item.item_id)
                exhausted = self.policy.is_exhausted(refreshed)
                results.append(
                    RelayRetryResult(
                        item_id=item.item_id,
                        disposition=(
                            RelayRetryDisposition.EXHAUSTED
                            if exhausted
                            else RelayRetryDisposition.FAILED
                        ),
                        attempt_count=refreshed.attempt_count,
                        next_attempt_at=(
                            None
                            if exhausted
                            else self.policy.next_attempt_at(refreshed)
                        ),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            self.queue.acknowledge(item.item_id)
            results.append(
                RelayRetryResult(
                    item_id=item.item_id,
                    disposition=RelayRetryDisposition.DELIVERED,
                    attempt_count=attempted.attempt_count,
                )
            )

        return tuple(results)
