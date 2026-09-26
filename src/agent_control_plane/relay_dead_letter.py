"""Durable dead-letter store for exhausted ACP relay forwards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional

from .authority import AuthorityValidationError
from .relay_forward_queue import DurableRelayForwardQueue, PendingRelayForward
from .relay_retry_policy import BoundedRelayRetryPolicy


RELAY_DEAD_LETTER_SCHEMA_VERSION = (
    "agent-control-plane.relay-dead-letter.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RelayDeadLetter:
    dead_letter_id: str
    item_id: str
    relay_id: str
    downstream_id: str
    payload_sha256: str
    payload: bytes
    attempt_count: int
    enqueued_at: str
    last_attempt_at: Optional[str]
    dead_lettered_at: str
    reason: str
    schema_version: str = RELAY_DEAD_LETTER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dead_letter_id",
            _required(self.dead_letter_id, "dead_letter_id"),
        )
        object.__setattr__(self, "item_id", _required(self.item_id, "item_id"))
        object.__setattr__(self, "relay_id", _required(self.relay_id, "relay_id"))
        object.__setattr__(
            self,
            "downstream_id",
            _required(self.downstream_id, "downstream_id"),
        )
        object.__setattr__(self, "reason", _required(self.reason, "reason"))
        if not isinstance(self.payload, bytes) or not self.payload:
            raise AuthorityValidationError("payload must be non-empty bytes")
        if hashlib.sha256(self.payload).hexdigest() != self.payload_sha256:
            raise AuthorityValidationError("payload_sha256 mismatch")
        if (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or self.attempt_count < 1
        ):
            raise AuthorityValidationError(
                "attempt_count must be an integer >= 1"
            )
        if self.schema_version != RELAY_DEAD_LETTER_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )


class DurableRelayDeadLetterStore:
    """SQLite-backed terminal store for explicitly exhausted relay forwards."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS relay_dead_letter (
                    dead_letter_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL UNIQUE,
                    relay_id TEXT NOT NULL,
                    downstream_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    enqueued_at TEXT NOT NULL,
                    last_attempt_at TEXT,
                    dead_lettered_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def _row(self, row: sqlite3.Row) -> RelayDeadLetter:
        return RelayDeadLetter(
            dead_letter_id=row["dead_letter_id"],
            item_id=row["item_id"],
            relay_id=row["relay_id"],
            downstream_id=row["downstream_id"],
            payload_sha256=row["payload_sha256"],
            payload=bytes(row["payload"]),
            attempt_count=row["attempt_count"],
            enqueued_at=row["enqueued_at"],
            last_attempt_at=row["last_attempt_at"],
            dead_lettered_at=row["dead_lettered_at"],
            reason=row["reason"],
            schema_version=row["schema_version"],
        )

    def get(self, item_id: str) -> RelayDeadLetter:
        identifier = _required(item_id, "item_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM relay_dead_letter WHERE item_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            raise AuthorityValidationError("unknown relay dead letter")
        return self._row(row)

    def all(self) -> tuple[RelayDeadLetter, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM relay_dead_letter
                ORDER BY dead_lettered_at, dead_letter_id
                """
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    def store(
        self,
        item: PendingRelayForward,
        *,
        reason: str,
        dead_lettered_at: Optional[str] = None,
    ) -> RelayDeadLetter:
        if not isinstance(item, PendingRelayForward):
            raise AuthorityValidationError(
                "item must be PendingRelayForward"
            )
        if item.attempt_count < 1:
            raise AuthorityValidationError(
                "cannot dead-letter an unattempted relay forward"
            )
        terminal_reason = _required(reason, "reason")
        timestamp = dead_lettered_at or _utc_now()
        dead_letter_id = (
            f"{item.relay_id}:{item.downstream_id}:"
            f"{item.payload_sha256}:{item.item_id}"
        )

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM relay_dead_letter WHERE item_id = ?",
                (item.item_id,),
            ).fetchone()
            if existing is not None:
                prior = self._row(existing)
                if (
                    prior.payload_sha256 != item.payload_sha256
                    or prior.relay_id != item.relay_id
                    or prior.downstream_id != item.downstream_id
                    or prior.attempt_count != item.attempt_count
                    or prior.reason != terminal_reason
                ):
                    raise AuthorityValidationError(
                        "relay dead-letter conflict"
                    )
                return prior

            connection.execute(
                """
                INSERT INTO relay_dead_letter (
                    dead_letter_id,
                    item_id,
                    relay_id,
                    downstream_id,
                    payload_sha256,
                    payload,
                    attempt_count,
                    enqueued_at,
                    last_attempt_at,
                    dead_lettered_at,
                    reason,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dead_letter_id,
                    item.item_id,
                    item.relay_id,
                    item.downstream_id,
                    item.payload_sha256,
                    item.payload,
                    item.attempt_count,
                    item.enqueued_at,
                    item.last_attempt_at,
                    timestamp,
                    terminal_reason,
                    RELAY_DEAD_LETTER_SCHEMA_VERSION,
                ),
            )
        return self.get(item.item_id)

    def move_from_queue(
        self,
        queue: DurableRelayForwardQueue,
        *,
        item_id: str,
        reason: str,
        dead_lettered_at: Optional[str] = None,
    ) -> RelayDeadLetter:
        if not isinstance(queue, DurableRelayForwardQueue):
            raise AuthorityValidationError(
                "queue must be DurableRelayForwardQueue"
            )
        identifier = _required(item_id, "item_id")
        item = queue.get(identifier)
        stored = self.store(
            item,
            reason=reason,
            dead_lettered_at=dead_lettered_at,
        )
        queue.acknowledge(identifier)
        return stored

    def manifest(self) -> dict[str, object]:
        entries = self.all()
        return {
            "schema": RELAY_DEAD_LETTER_SCHEMA_VERSION,
            "database_path": self.database_path,
            "dead_letter_count": len(entries),
            "dead_letters": [
                {
                    "dead_letter_id": entry.dead_letter_id,
                    "item_id": entry.item_id,
                    "relay_id": entry.relay_id,
                    "downstream_id": entry.downstream_id,
                    "payload_sha256": entry.payload_sha256,
                    "attempt_count": entry.attempt_count,
                    "enqueued_at": entry.enqueued_at,
                    "last_attempt_at": entry.last_attempt_at,
                    "dead_lettered_at": entry.dead_lettered_at,
                    "reason": entry.reason,
                }
                for entry in entries
            ],
        }



def dead_letter_exhausted(
    *,
    queue: DurableRelayForwardQueue,
    store: DurableRelayDeadLetterStore,
    policy: BoundedRelayRetryPolicy,
    reason: str = "retry attempts exhausted",
    dead_lettered_at: Optional[str] = None,
) -> tuple[str, ...]:
    """Move only policy-exhausted pending items into durable dead-letter state."""
    if not isinstance(queue, DurableRelayForwardQueue):
        raise AuthorityValidationError(
            "queue must be DurableRelayForwardQueue"
        )
    if not isinstance(store, DurableRelayDeadLetterStore):
        raise AuthorityValidationError(
            "store must be DurableRelayDeadLetterStore"
        )
    if not isinstance(policy, BoundedRelayRetryPolicy):
        raise AuthorityValidationError(
            "policy must be BoundedRelayRetryPolicy"
        )

    moved: list[str] = []
    for item in queue.pending():
        if not policy.is_exhausted(item):
            continue
        store.move_from_queue(
            queue,
            item_id=item.item_id,
            reason=reason,
            dead_lettered_at=dead_lettered_at,
        )
        moved.append(item.item_id)
    return tuple(moved)
