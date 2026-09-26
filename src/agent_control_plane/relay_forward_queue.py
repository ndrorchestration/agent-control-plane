"""Durable pending-forward queue for signed ACP relay-chain payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import sqlite3
from pathlib import Path
from typing import Callable, Iterable, Optional

from .authority import AuthorityValidationError


RELAY_FORWARD_QUEUE_SCHEMA_VERSION = (
    "agent-control-plane.relay-forward-queue.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PendingRelayForward:
    item_id: str
    relay_id: str
    downstream_id: str
    payload_sha256: str
    payload: bytes
    enqueued_at: str
    attempt_count: int
    last_attempt_at: Optional[str]
    schema_version: str = RELAY_FORWARD_QUEUE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _required(self.item_id, "item_id"))
        object.__setattr__(self, "relay_id", _required(self.relay_id, "relay_id"))
        object.__setattr__(
            self,
            "downstream_id",
            _required(self.downstream_id, "downstream_id"),
        )
        if not isinstance(self.payload, bytes) or not self.payload:
            raise AuthorityValidationError("payload must be non-empty bytes")
        digest = hashlib.sha256(self.payload).hexdigest()
        if self.payload_sha256 != digest:
            raise AuthorityValidationError("payload_sha256 mismatch")
        if (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or self.attempt_count < 0
        ):
            raise AuthorityValidationError(
                "attempt_count must be an integer >= 0"
            )
        if self.schema_version != RELAY_FORWARD_QUEUE_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )


class DurableRelayForwardQueue:
    """SQLite-backed queue of pending signed relay-chain forwards."""

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
                CREATE TABLE IF NOT EXISTS relay_forward_queue (
                    item_id TEXT PRIMARY KEY,
                    relay_id TEXT NOT NULL,
                    downstream_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    enqueued_at TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_attempt_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def enqueue(
        self,
        *,
        relay_id: str,
        downstream_id: str,
        payload: bytes,
        item_id: Optional[str] = None,
        enqueued_at: Optional[str] = None,
    ) -> PendingRelayForward:
        relay = _required(relay_id, "relay_id")
        downstream = _required(downstream_id, "downstream_id")
        if not isinstance(payload, bytes) or not payload:
            raise AuthorityValidationError("payload must be non-empty bytes")
        digest = hashlib.sha256(payload).hexdigest()
        identifier = item_id or f"{relay}:{downstream}:{digest}"
        queued_at = enqueued_at or _utc_now()

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM relay_forward_queue WHERE item_id = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                prior = self._row(existing)
                if (
                    prior.relay_id != relay
                    or prior.downstream_id != downstream
                    or prior.payload != payload
                ):
                    raise AuthorityValidationError(
                        "relay forward item_id conflict"
                    )
                return prior

            connection.execute(
                """
                INSERT INTO relay_forward_queue (
                    item_id,
                    relay_id,
                    downstream_id,
                    payload_sha256,
                    payload,
                    enqueued_at,
                    attempt_count,
                    last_attempt_at,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)
                """,
                (
                    identifier,
                    relay,
                    downstream,
                    digest,
                    payload,
                    queued_at,
                    RELAY_FORWARD_QUEUE_SCHEMA_VERSION,
                ),
            )
        return self.get(identifier)

    def _row(self, row: sqlite3.Row) -> PendingRelayForward:
        return PendingRelayForward(
            item_id=row["item_id"],
            relay_id=row["relay_id"],
            downstream_id=row["downstream_id"],
            payload_sha256=row["payload_sha256"],
            payload=bytes(row["payload"]),
            enqueued_at=row["enqueued_at"],
            attempt_count=row["attempt_count"],
            last_attempt_at=row["last_attempt_at"],
            schema_version=row["schema_version"],
        )

    def get(self, item_id: str) -> PendingRelayForward:
        identifier = _required(item_id, "item_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM relay_forward_queue WHERE item_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            raise AuthorityValidationError("unknown relay forward item")
        return self._row(row)

    def pending(self) -> tuple[PendingRelayForward, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM relay_forward_queue
                ORDER BY enqueued_at, item_id
                """
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    def mark_attempt(
        self,
        item_id: str,
        *,
        attempted_at: Optional[str] = None,
    ) -> PendingRelayForward:
        identifier = _required(item_id, "item_id")
        when = attempted_at or _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE relay_forward_queue
                SET attempt_count = attempt_count + 1,
                    last_attempt_at = ?
                WHERE item_id = ?
                """,
                (when, identifier),
            )
            if cursor.rowcount != 1:
                raise AuthorityValidationError("unknown relay forward item")
        return self.get(identifier)

    def acknowledge(self, item_id: str) -> None:
        identifier = _required(item_id, "item_id")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM relay_forward_queue WHERE item_id = ?",
                (identifier,),
            )
            if cursor.rowcount != 1:
                raise AuthorityValidationError("unknown relay forward item")

    def forward(
        self,
        *,
        relay_id: str,
        downstream_id: str,
        payload: bytes,
        exchange: Callable[[bytes], bytes],
        item_id: Optional[str] = None,
    ) -> bytes:
        if not callable(exchange):
            raise AuthorityValidationError("exchange must be callable")
        item = self.enqueue(
            relay_id=relay_id,
            downstream_id=downstream_id,
            payload=payload,
            item_id=item_id,
        )
        self.mark_attempt(item.item_id)
        response = exchange(item.payload)
        if not isinstance(response, bytes):
            raise AuthorityValidationError(
                "relay downstream exchange must return bytes"
            )
        self.acknowledge(item.item_id)
        return response

    def drain(
        self,
        *,
        exchange_for: Callable[[str], Callable[[bytes], bytes]],
        stop_on_error: bool = True,
    ) -> tuple[str, ...]:
        if not callable(exchange_for):
            raise AuthorityValidationError("exchange_for must be callable")
        completed: list[str] = []
        for item in self.pending():
            try:
                exchange = exchange_for(item.downstream_id)
                if not callable(exchange):
                    raise AuthorityValidationError(
                        "exchange_for must return a callable"
                    )
                self.mark_attempt(item.item_id)
                response = exchange(item.payload)
                if not isinstance(response, bytes):
                    raise AuthorityValidationError(
                        "relay downstream exchange must return bytes"
                    )
                self.acknowledge(item.item_id)
                completed.append(item.item_id)
            except Exception:
                if stop_on_error:
                    raise
        return tuple(completed)

    def manifest(self) -> dict[str, object]:
        items = self.pending()
        return {
            "schema": RELAY_FORWARD_QUEUE_SCHEMA_VERSION,
            "database_path": self.database_path,
            "pending_count": len(items),
            "pending": [
                {
                    "item_id": item.item_id,
                    "relay_id": item.relay_id,
                    "downstream_id": item.downstream_id,
                    "payload_sha256": item.payload_sha256,
                    "enqueued_at": item.enqueued_at,
                    "attempt_count": item.attempt_count,
                    "last_attempt_at": item.last_attempt_at,
                }
                for item in items
            ],
        }
