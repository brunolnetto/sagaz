"""
Schema creation and migration for ``SQLiteOutboxStorage``.

Creates the ``outbox_events`` table and adds columns introduced after the
table was first created, normalising legacy rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sagaz.core.storage.backends.sqlite._outbox_base import SQLiteOutboxMixinBase

if TYPE_CHECKING:
    import aiosqlite


class SQLiteOutboxSchemaMixin(SQLiteOutboxMixinBase):
    """Create and upgrade the ``outbox_events`` table."""

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._conn
        if conn is None:
            msg = "Connection not initialized"
            raise RuntimeError(msg)
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS outbox_events (
                event_id TEXT PRIMARY KEY,
                saga_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                sent_at TEXT,
                worker_id TEXT,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                aggregate_type TEXT,
                aggregate_id TEXT,
                headers TEXT,
                routing_key TEXT,
                partition_key TEXT,
                dead_letter_at TEXT,
                dead_letter_reason TEXT,
                error_type TEXT,
                error_classification TEXT,
                error_fingerprint TEXT,
                replay_count INTEGER DEFAULT 0,
                tenant_id TEXT NOT NULL DEFAULT 'default'
            );

            CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status);
            CREATE INDEX IF NOT EXISTS idx_outbox_saga_id ON outbox_events(saga_id);
        """)
        await self._ensure_optional_columns(conn)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_claimed_at ON outbox_events(claimed_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_tenant_id ON outbox_events(tenant_id, status)"
        )
        assert conn is not None
        await conn.commit()

    async def _ensure_optional_columns(self, conn: aiosqlite.Connection) -> None:
        """Add newer optional columns when the table already exists."""
        cursor = await conn.execute("PRAGMA table_info(outbox_events)")
        rows = await cursor.fetchall()
        existing_columns = {row["name"] for row in rows}

        optional_columns = (
            ("dead_letter_at", "TEXT"),
            ("dead_letter_reason", "TEXT"),
            ("error_type", "TEXT"),
            ("error_classification", "TEXT"),
            ("error_fingerprint", "TEXT"),
            ("replay_count", "INTEGER DEFAULT 0"),
            ("aggregate_type", "TEXT"),
            ("aggregate_id", "TEXT"),
            ("headers", "TEXT"),
            ("routing_key", "TEXT"),
            ("partition_key", "TEXT"),
            ("claimed_at", "TEXT"),
            ("sent_at", "TEXT"),
            ("worker_id", "TEXT"),
            ("retry_count", "INTEGER DEFAULT 0"),
            ("last_error", "TEXT"),
            # ADR-020: rows written before multi-tenancy belong to 'default'.
            ("tenant_id", "TEXT NOT NULL DEFAULT 'default'"),
        )

        for column_name, column_type in optional_columns:
            if column_name not in existing_columns:
                await conn.execute(
                    f"ALTER TABLE outbox_events ADD COLUMN {column_name} {column_type}"
                )

        # Legacy rows predate optional metadata columns. Normalize them before
        # export so they remain valid when imported into stricter backends.
        await conn.execute(
            """
            UPDATE outbox_events
            SET aggregate_type = COALESCE(aggregate_type, 'saga'),
                aggregate_id = COALESCE(aggregate_id, saga_id),
                headers = COALESCE(headers, '{}'),
                retry_count = COALESCE(retry_count, 0)
            """
        )
