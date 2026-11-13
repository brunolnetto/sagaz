"""
Counting, export and import of outbox events for ``SQLiteOutboxStorage``.

Used by storage transfer/migration tooling to move events between backends.
"""

from __future__ import annotations

from typing import Any

from sagaz.core.outbox.types import OutboxEvent
from sagaz.core.storage.backends.sqlite._outbox_base import SQLiteOutboxMixinBase
from sagaz.core.storage.backends.sqlite._outbox_rows import SQLiteOutboxRowMappingMixin
from sagaz.core.storage.interfaces.outbox import OutboxStorageError


class SQLiteOutboxTransferMixin(SQLiteOutboxRowMappingMixin, SQLiteOutboxMixinBase):
    """``count``/``export_all``/``import_record`` over ``outbox_events``."""

    async def count(self) -> int:
        """Count total events."""
        conn = await self._get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM outbox_events")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def export_all(self):
        """Export all records for transfer."""
        conn = await self._get_connection()
        cursor = await conn.execute("SELECT * FROM outbox_events ORDER BY event_id")

        async for row in cursor:
            event = self._row_to_event(row)
            yield event.to_dict()

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import an event without overwriting existing destination state."""
        event = OutboxEvent.from_dict(record)
        existing = await self.get_by_id(event.event_id)

        if existing is not None:
            if existing != event:
                msg = f"Outbox event {event.event_id} already exists with different state"
                raise OutboxStorageError(msg)
            return

        await self.insert(event)
