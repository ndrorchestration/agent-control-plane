"""Durable append-only persistence for ACP synchronization watermarks."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Mapping, Set

from .authority import AuthorityValidationError
from .authority_sync_watermark import (
    AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION,
    AuthoritySyncWatermark,
    AuthoritySyncWatermarkRegistry,
    WatermarkDisposition,
    decode_authority_sync_watermark,
    encode_authority_sync_watermark,
)


AUTHORITY_SYNC_WATERMARK_LOG_SCHEMA_VERSION = (
    "agent-control-plane.authority-sync-watermark-log.v0-candidate"
)


class SqliteAuthoritySyncWatermarkLog:
    """Append-only canonical watermark log with content verification."""

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        if not isinstance(database_path, (str, os.PathLike)):
            raise AuthorityValidationError("database_path must be a path")
        raw = os.fspath(database_path)
        if not raw.strip():
            raise AuthorityValidationError("database_path must not be blank")
        self.database_path = Path(raw)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.database_path), timeout=30.0)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS watermark_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS applied_watermarks (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                    watermark_id TEXT NOT NULL UNIQUE,
                    issuer_id TEXT NOT NULL,
                    target_sender_id TEXT NOT NULL,
                    min_sequence INTEGER NOT NULL CHECK (min_sequence >= 0),
                    content_sha256 TEXT NOT NULL,
                    payload BLOB NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO watermark_metadata(key, value) VALUES (?, ?)",
                ("schema_version", AUTHORITY_SYNC_WATERMARK_LOG_SCHEMA_VERSION),
            )
            row = connection.execute(
                "SELECT value FROM watermark_metadata WHERE key = ?",
                ("schema_version",),
            ).fetchone()
            if row is None or row[0] != AUTHORITY_SYNC_WATERMARK_LOG_SCHEMA_VERSION:
                raise AuthorityValidationError(
                    "unsupported authority sync watermark log schema"
                )

    def append(self, watermark: AuthoritySyncWatermark) -> None:
        payload = encode_authority_sync_watermark(watermark)
        digest = hashlib.sha256(payload).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT issuer_id, target_sender_id, min_sequence, content_sha256, payload
                FROM applied_watermarks
                WHERE watermark_id = ?
                """,
                (watermark.watermark_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing[0] == watermark.issuer_id
                    and existing[1] == watermark.target_sender_id
                    and existing[2] == watermark.min_sequence
                    and existing[3] == digest
                    and bytes(existing[4]) == payload
                ):
                    return
                raise AuthorityValidationError(
                    "durable authority sync watermark_id conflict"
                )
            connection.execute(
                """
                INSERT INTO applied_watermarks(
                    watermark_id, issuer_id, target_sender_id,
                    min_sequence, content_sha256, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    watermark.watermark_id,
                    watermark.issuer_id,
                    watermark.target_sender_id,
                    watermark.min_sequence,
                    digest,
                    sqlite3.Binary(payload),
                ),
            )

    def load(self) -> tuple[AuthoritySyncWatermark, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ordinal, watermark_id, issuer_id, target_sender_id,
                       min_sequence, content_sha256, payload
                FROM applied_watermarks
                ORDER BY ordinal ASC
                """
            ).fetchall()

        result = []
        for ordinal, watermark_id, issuer_id, target_sender_id, min_sequence, digest, raw in rows:
            payload = bytes(raw)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise AuthorityValidationError(
                    f"authority sync watermark log content hash mismatch at ordinal {ordinal}"
                )
            watermark = decode_authority_sync_watermark(payload)
            if encode_authority_sync_watermark(watermark) != payload:
                raise AuthorityValidationError(
                    f"authority sync watermark log contains non-canonical payload at ordinal {ordinal}"
                )
            if (
                watermark.watermark_id != watermark_id
                or watermark.issuer_id != issuer_id
                or watermark.target_sender_id != target_sender_id
                or watermark.min_sequence != min_sequence
            ):
                raise AuthorityValidationError(
                    f"authority sync watermark log index mismatch at ordinal {ordinal}"
                )
            result.append(watermark)
        return tuple(result)

    def manifest(self) -> dict[str, object]:
        watermarks = self.load()
        digests = [
            hashlib.sha256(encode_authority_sync_watermark(item)).hexdigest()
            for item in watermarks
        ]
        return {
            "schema": AUTHORITY_SYNC_WATERMARK_LOG_SCHEMA_VERSION,
            "watermark_schema": AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION,
            "watermark_count": len(watermarks),
            "content_root_sha256": hashlib.sha256(
                "\n".join(digests).encode("ascii")
            ).hexdigest(),
        }


class DurableAuthoritySyncWatermarkRegistry(AuthoritySyncWatermarkRegistry):
    """Trusted watermark registry reconstructed from a durable canonical log."""

    def __init__(
        self,
        trusted_issuers: Mapping[str, Set[str] | tuple[str, ...] | list[str]],
        *,
        database_path: str | os.PathLike[str],
    ) -> None:
        self.log = SqliteAuthoritySyncWatermarkLog(database_path)
        self._trusted_config = trusted_issuers
        super().__init__(trusted_issuers)
        self._restore_from_log()

    def _restore_from_log(self) -> None:
        super().__init__(self._trusted_config)
        for watermark in self.log.load():
            disposition = super().apply(watermark)
            if disposition is not WatermarkDisposition.APPLIED:
                raise AuthorityValidationError(
                    "durable authority sync watermark log failed canonical replay"
                )

    def apply(self, watermark: AuthoritySyncWatermark) -> WatermarkDisposition:
        disposition = super().apply(watermark)
        if disposition is WatermarkDisposition.DUPLICATE:
            return disposition
        try:
            self.log.append(watermark)
        except Exception as exc:
            self._restore_from_log()
            if isinstance(exc, AuthorityValidationError):
                raise
            raise AuthorityValidationError(
                "durable authority sync watermark persistence failed"
            ) from exc
        return disposition

    def manifest(self) -> dict[str, object]:
        manifest = super().manifest()
        manifest["persistence"] = self.log.manifest()
        return manifest
