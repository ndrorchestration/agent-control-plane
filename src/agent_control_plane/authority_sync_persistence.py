"""Durable append-only persistence for ACP authority synchronization."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Iterable

from .authority import AuthorityValidationError
from .authority_state import InMemoryAuthorityStateCache
from .authority_sync import (
    AUTHORITY_SYNC_SCHEMA_VERSION,
    AuthoritySyncReconciler,
    SyncDisposition,
    SyncMessage,
    decode_sync_message,
    encode_sync_message,
    sync_message_sha256,
)
from .revocation import InMemoryRevocationRegistry


AUTHORITY_SYNC_LOG_SCHEMA_VERSION = "agent-control-plane.authority-sync-log.v0-candidate"


class SqliteAuthoritySyncLog:
    """Append-only canonical ACP sync messages persisted in SQLite.

    The log stores only messages that the canonical reconciler accepted as
    APPLIED. Recovery replays those exact canonical payloads through the same
    reconciler rather than reconstructing authority state with a second set of
    reconciliation rules.
    """

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        if not isinstance(database_path, (str, os.PathLike)):
            raise AuthorityValidationError("database_path must be a path")
        raw_path = os.fspath(database_path)
        if not raw_path.strip():
            raise AuthorityValidationError("database_path must not be blank")
        self.database_path = Path(raw_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=30.0)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS applied_messages (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    sender_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK (sequence >= 0),
                    content_sha256 TEXT NOT NULL,
                    payload BLOB NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", AUTHORITY_SYNC_LOG_SCHEMA_VERSION),
            )
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?",
                ("schema_version",),
            ).fetchone()
            if row is None or row[0] != AUTHORITY_SYNC_LOG_SCHEMA_VERSION:
                raise AuthorityValidationError("unsupported authority sync log schema")

    def append(self, message: SyncMessage) -> None:
        payload = encode_sync_message(message)
        digest = sync_message_sha256(message)
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT sender_id, sequence, content_sha256, payload
                FROM applied_messages
                WHERE message_id = ?
                """,
                (message.message_id,),
            ).fetchone()
            if existing is not None:
                existing_payload = bytes(existing[3])
                if (
                    existing[0] == message.sender_id
                    and existing[1] == message.sequence
                    and existing[2] == digest
                    and existing_payload == payload
                ):
                    return
                raise AuthorityValidationError(
                    "durable authority sync message_id conflict"
                )
            connection.execute(
                """
                INSERT INTO applied_messages(
                    message_id, sender_id, sequence, content_sha256, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.sender_id,
                    message.sequence,
                    digest,
                    sqlite3.Binary(payload),
                ),
            )

    def load_messages(self) -> tuple[SyncMessage, ...]:
        messages: list[SyncMessage] = []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ordinal, message_id, sender_id, sequence, content_sha256, payload
                FROM applied_messages
                ORDER BY ordinal ASC
                """
            ).fetchall()

        for ordinal, message_id, sender_id, sequence, digest, raw_payload in rows:
            payload = bytes(raw_payload)
            actual_digest = hashlib.sha256(payload).hexdigest()
            if actual_digest != digest:
                raise AuthorityValidationError(
                    f"authority sync log content hash mismatch at ordinal {ordinal}"
                )
            message = decode_sync_message(payload)
            if encode_sync_message(message) != payload:
                raise AuthorityValidationError(
                    f"authority sync log contains non-canonical payload at ordinal {ordinal}"
                )
            if (
                message.message_id != message_id
                or message.sender_id != sender_id
                or message.sequence != sequence
            ):
                raise AuthorityValidationError(
                    f"authority sync log index mismatch at ordinal {ordinal}"
                )
            if sync_message_sha256(message) != digest:
                raise AuthorityValidationError(
                    f"authority sync log decoded hash mismatch at ordinal {ordinal}"
                )
            messages.append(message)
        return tuple(messages)

    def manifest(self) -> dict[str, object]:
        messages = self.load_messages()
        digests = [sync_message_sha256(message) for message in messages]
        root_input = "\n".join(digests).encode("ascii")
        return {
            "schema": AUTHORITY_SYNC_LOG_SCHEMA_VERSION,
            "authority_sync_schema": AUTHORITY_SYNC_SCHEMA_VERSION,
            "message_count": len(messages),
            "content_root_sha256": hashlib.sha256(root_input).hexdigest(),
        }


class DurableAuthoritySyncReconciler(AuthoritySyncReconciler):
    """Authority reconciler recovered from an append-only canonical SQLite log."""

    def __init__(
        self,
        *,
        receiver_id: str,
        database_path: str | os.PathLike[str],
    ) -> None:
        self.log = SqliteAuthoritySyncLog(database_path)
        super().__init__(
            receiver_id=receiver_id,
            state_cache=InMemoryAuthorityStateCache(),
            revocations=InMemoryRevocationRegistry(),
        )
        self._restore_from_log()

    def _restore_from_log(self) -> None:
        self.state_cache = InMemoryAuthorityStateCache()
        self.revocations = InMemoryRevocationRegistry()
        self._message_fingerprints = {}
        self._sender_sequences = {}

        for message in self.log.load_messages():
            acknowledgement = super().apply(message)
            if acknowledgement.disposition is not SyncDisposition.APPLIED:
                raise AuthorityValidationError(
                    "durable authority sync log failed canonical replay: "
                    f"{acknowledgement.reason_code}"
                )

    def apply(self, message: SyncMessage):
        acknowledgement = super().apply(message)
        if acknowledgement.disposition is not SyncDisposition.APPLIED:
            return acknowledgement

        try:
            self.log.append(message)
        except Exception as exc:
            # The durable log is authoritative across restarts. Reconstruct the
            # process-local projection from the last committed durable prefix so
            # a failed persistence attempt cannot leave memory ahead of storage.
            self._restore_from_log()
            if isinstance(exc, AuthorityValidationError):
                raise
            raise AuthorityValidationError(
                "durable authority sync persistence failed"
            ) from exc
        return acknowledgement

    def manifest(self) -> dict[str, object]:
        manifest = super().manifest()
        manifest["persistence"] = self.log.manifest()
        return manifest
