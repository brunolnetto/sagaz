"""
Dead-letter queue operations for ``PostgreSQLOutboxStorage``.
"""

from datetime import UTC, datetime, timedelta

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus, ReplayLoopError
from sagaz.core.storage.backends.postgresql._outbox_base import PostgreSQLOutboxMixinBase
from sagaz.core.storage.backends.postgresql._outbox_rows import (
    PostgreSQLOutboxRowMappingMixin,
)
from sagaz.core.storage.backends.postgresql._outbox_tenancy import (
    scoped_connection,
    tenant_param,
    tenant_predicate,
)


class PostgreSQLOutboxDeadLetterMixin(PostgreSQLOutboxRowMappingMixin, PostgreSQLOutboxMixinBase):
    """List, replay and purge dead-letter events."""

    async def get_dead_letter_events(
        self,
        limit: int = 100,
    ) -> list[OutboxEvent]:
        """Get events in dead letter queue."""
        query = f"""
            SELECT * FROM saga_outbox
            WHERE status = 'dead_letter' AND {tenant_predicate(2)}
            ORDER BY created_at DESC
            LIMIT $1
        """

        async with scoped_connection(self._pool) as conn:
            rows = await conn.fetch(query, limit, tenant_param())
            return [self._row_to_event(row) for row in rows]

    async def requeue_dead_letter_event(self, event_id: str, force: bool = False) -> OutboxEvent:
        """Move a dead-letter event back to PENDING for replay."""
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
        event.dead_letter_at = None
        event.dead_letter_reason = None
        event.worker_id = None
        event.claimed_at = None
        return await self.update_status(event_id, OutboxStatus.PENDING, event=event)

    async def purge_dead_letter_events(self, older_than: timedelta | None = None) -> int:
        """Permanently remove dead-letter events."""
        async with scoped_connection(self._pool) as conn:
            if older_than is None:
                result = await conn.execute(
                    f"DELETE FROM saga_outbox WHERE status = 'dead_letter' AND {tenant_predicate(1)}",
                    tenant_param(),
                )
            else:
                cutoff = datetime.now(UTC) - older_than
                result = await conn.execute(
                    f"""
                    DELETE FROM saga_outbox
                    WHERE status = 'dead_letter'
                    AND dead_letter_at IS NOT NULL
                    AND dead_letter_at < $1
                    AND {tenant_predicate(2)}
                    """,
                    cutoff,
                    tenant_param(),
                )
            return int(result.split()[-1]) if result.startswith("DELETE") else 0
