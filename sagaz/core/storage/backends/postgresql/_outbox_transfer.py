"""
Counting, export and import of outbox events for ``PostgreSQLOutboxStorage``.

Used by storage transfer/migration tooling to move events between backends.
Both the active and the archive table are covered.
"""

from typing import Any

from sagaz.core.outbox.types import OutboxEvent
from sagaz.core.storage.backends.postgresql._outbox_base import PostgreSQLOutboxMixinBase
from sagaz.core.storage.backends.postgresql._outbox_rows import (
    PostgreSQLOutboxRowMappingMixin,
)
from sagaz.core.storage.interfaces.outbox import OutboxStorageError


class PostgreSQLOutboxTransferMixin(PostgreSQLOutboxRowMappingMixin, PostgreSQLOutboxMixinBase):
    """``count``/``export_all``/``import_record`` across active and archived rows."""

    async def count(self) -> int:
        """Count total events."""
        if not self._pool:
            # If not initialized, maybe zero? Or raise error?
            # Assuming initialized for now as it's required for other ops
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT
                    (SELECT COUNT(*) FROM saga_outbox)
                    + (SELECT COUNT(*) FROM saga_outbox_archive)
                """
            )
            return int(count)

    async def export_all(self):
        """Export active and archived outbox records for transfer."""
        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                try:
                    cursor = conn.cursor(
                        """
                        SELECT * FROM saga_outbox
                        UNION ALL
                        SELECT * FROM saga_outbox_archive
                        ORDER BY event_id
                        """
                    )
                    async for row in cursor:
                        event = self._row_to_event(row)
                        yield event.to_dict()
                except Exception:  # pylint: disable=try-except-raise
                    # Transaction rollback is automatic with context manager
                    raise

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import without overwriting existing active or archived state."""
        event = OutboxEvent.from_dict(record)

        if not self._pool:
            msg = "Storage not initialized"
            raise OutboxStorageError(msg)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Serialize concurrent migration imports for the same event.
                await conn.fetchval(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    event.event_id,
                )

                row = await conn.fetchrow(
                    """
                    SELECT * FROM saga_outbox
                    WHERE event_id = $1
                    FOR UPDATE
                    """,
                    event.event_id,
                )

                if row is None:
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM saga_outbox_archive
                        WHERE event_id = $1
                        FOR UPDATE
                        """,
                        event.event_id,
                    )

                if row is not None:
                    existing = self._row_to_event(row)
                    if existing != event:
                        msg = f"Outbox event {event.event_id} already exists with different state"
                        raise OutboxStorageError(msg)
                    return

                # insert() now uses a plain INSERT, never an upsert.
                await self.insert(event, connection=conn)
