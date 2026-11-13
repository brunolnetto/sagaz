"""
Dead-letter queue operations for ``SQLiteOutboxStorage``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus, ReplayLoopError
from sagaz.core.storage.backends.sqlite._outbox_base import SQLiteOutboxMixinBase
from sagaz.core.storage.backends.sqlite._outbox_rows import SQLiteOutboxRowMappingMixin


class SQLiteOutboxDeadLetterMixin(SQLiteOutboxRowMappingMixin, SQLiteOutboxMixinBase):
    """List, replay and purge dead-letter events."""

    async def get_dead_letter_events(self, limit: int = 100) -> list[OutboxEvent]:
        """Get events in dead letter status."""
        conn = await self._get_connection()

        cursor = await conn.execute(
            """
            SELECT * FROM outbox_events
            WHERE status = 'dead_letter'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()

        return [self._row_to_event(row) for row in rows]

    async def requeue_dead_letter_event(self, event_id: str, force: bool = False) -> OutboxEvent:
        """Move a DLQ event back to PENDING for replay."""
        event = await self.get_by_id(event_id)
        if event is None:
            msg = f"Event {event_id} not found"
            raise KeyError(msg)

        max_replays = 3
        if not force and event.replay_count >= max_replays:
            raise ReplayLoopError(
                event_id=event_id,
                replay_count=event.replay_count,
                max_replays=max_replays,
            )

        event.replay_count += 1
        event.retry_count = 0
        event.worker_id = None
        event.claimed_at = None
        event.dead_letter_at = None
        event.dead_letter_reason = None
        updated = await self.update_status(event_id, OutboxStatus.PENDING, event=event)
        if updated is None:
            msg = f"Event {event_id} not found"
            raise KeyError(msg)
        return updated

    async def purge_dead_letter_events(
        self,
        older_than: timedelta | None = None,
    ) -> int:
        """Permanently remove DLQ events."""
        conn = await self._get_connection()

        if older_than is None:
            cursor = await conn.execute("DELETE FROM outbox_events WHERE status = 'dead_letter'")
        else:
            cutoff = (datetime.now(UTC) - older_than).isoformat()
            cursor = await conn.execute(
                """
                DELETE FROM outbox_events
                WHERE status = 'dead_letter'
                AND dead_letter_at IS NOT NULL
                AND dead_letter_at < ?
                """,
                (cutoff,),
            )
        await conn.commit()
        return cursor.rowcount
