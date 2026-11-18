"""
Housekeeping queries for ``PostgreSQLOutboxStorage``: stuck-claim detection and
release, and archiving of sent events.
"""

from datetime import UTC, datetime, timedelta

from sagaz.core.outbox.types import OutboxEvent
from sagaz.core.storage.backends.postgresql._outbox_base import PostgreSQLOutboxMixinBase
from sagaz.core.storage.backends.postgresql._outbox_rows import (
    PostgreSQLOutboxRowMappingMixin,
)
from sagaz.core.storage.backends.postgresql._outbox_tenancy import (
    scoped_connection,
    tenant_param,
    tenant_predicate,
)


class PostgreSQLOutboxMaintenanceMixin(PostgreSQLOutboxRowMappingMixin, PostgreSQLOutboxMixinBase):
    """Recover stuck claims and archive sent events."""

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """Get events that appear to be stuck."""
        cutoff = datetime.now(UTC) - timedelta(seconds=claimed_older_than_seconds)

        query = f"""
            SELECT * FROM saga_outbox
            WHERE status = 'claimed'
            AND claimed_at < $1
            AND {tenant_predicate(2)}
            ORDER BY claimed_at
        """

        async with scoped_connection(self._pool) as conn:
            rows = await conn.fetch(query, cutoff, tenant_param())
            return [self._row_to_event(row) for row in rows]

    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:
        """Release stuck events back to PENDING status."""
        cutoff = datetime.now(UTC) - timedelta(seconds=claimed_older_than_seconds)

        query = f"""
            UPDATE saga_outbox
            SET status = 'pending',
                worker_id = NULL,
                claimed_at = NULL
            WHERE status = 'claimed'
            AND claimed_at < $1
            AND {tenant_predicate(2)}
        """

        async with scoped_connection(self._pool) as conn:
            result = await conn.execute(query, cutoff, tenant_param())
            # Parse "UPDATE N" to get count
            return int(result.split()[-1])

    async def archive_sent_events(
        self,
        older_than_days: int = 7,
    ) -> int:
        """Move old sent events to archive table."""
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

        async with scoped_connection(self._pool) as conn, conn.transaction():
            # Copy to archive
            insert_query = f"""
                    INSERT INTO saga_outbox_archive
                    SELECT * FROM saga_outbox
                    WHERE status = 'sent' AND sent_at < $1 AND {tenant_predicate(2)}
                """
            await conn.execute(insert_query, cutoff, tenant_param())

            # Delete from main table
            delete_query = f"""
                    DELETE FROM saga_outbox
                    WHERE status = 'sent' AND sent_at < $1 AND {tenant_predicate(2)}
                """
            result = await conn.execute(delete_query, cutoff, tenant_param())
            return int(result.split()[-1])
