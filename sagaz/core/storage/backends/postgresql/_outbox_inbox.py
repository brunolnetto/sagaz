"""
Consumer inbox (idempotent consumption) for ``PostgreSQLOutboxStorage``.

Inbox rows belong to the tenant of the scope that consumed the event
(ADR-020): consumers should run inside ``tenant_scope(<tenant_id header>)``.
"""

import json
from typing import TYPE_CHECKING, Any, cast

from sagaz.core.storage._tenancy import write_tenant
from sagaz.core.storage.backends.postgresql._outbox_base import PostgreSQLOutboxMixinBase
from sagaz.core.storage.backends.postgresql._outbox_tenancy import (
    scoped_connection,
    tenant_param,
    tenant_predicate,
)

try:
    import asyncpg
except ImportError:  # pragma: no cover - asyncpg is optional
    asyncpg = cast(Any, None)

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg as asyncpg_types


class PostgreSQLOutboxInboxMixin(PostgreSQLOutboxMixinBase):
    """``consumer_inbox`` deduplication, timing and cleanup."""

    async def check_and_insert_inbox(
        self,
        event_id: str,
        consumer_name: str,
        source_topic: str,
        event_type: str,
        payload: dict,
        connection: "asyncpg_types.Connection | None" = None,
    ) -> bool:
        """
        Check if event was already processed and insert if not.

        Args:
            event_id: Event identifier
            consumer_name: Consumer service name
            source_topic: Source topic/queue
            event_type: Event type
            payload: Event payload
            connection: Optional connection for transactions

        Returns:
            True if duplicate (already processed), False if new
        """

        async def _execute(conn):
            try:
                await conn.execute(
                    """
                    INSERT INTO consumer_inbox (
                        event_id, consumer_name, source_topic,
                        event_type, payload, consumed_at, tenant_id
                    )
                    VALUES ($1, $2, $3, $4, $5, NOW(), $6)
                    """,
                    event_id,
                    consumer_name,
                    source_topic,
                    event_type,
                    json.dumps(payload),
                    write_tenant(),
                )
                return False  # Not a duplicate
            except asyncpg.UniqueViolationError:
                return True  # Duplicate

        if connection:
            async with scoped_connection(self._pool, connection) as conn:
                return await _execute(conn)  # type: ignore[no-any-return]
        async with scoped_connection(self._pool) as conn, conn.transaction():
            return await _execute(conn)  # type: ignore[no-any-return]

    async def update_inbox_duration(self, event_id: str, duration_ms: int) -> None:
        """Update processing duration for an event."""
        async with scoped_connection(self._pool) as conn:
            await conn.execute(
                f"""
                UPDATE consumer_inbox
                SET processing_duration_ms = $1
                WHERE event_id = $2 AND {tenant_predicate(3)}
                """,
                duration_ms,
                event_id,
                tenant_param(),
            )

    async def cleanup_inbox(self, consumer_name: str, older_than_days: int) -> int:
        """
        Delete old inbox entries.

        Returns:
            Number of entries deleted
        """
        async with scoped_connection(self._pool) as conn:
            result = await conn.execute(
                f"""
                DELETE FROM consumer_inbox
                WHERE consumer_name = $1
                AND consumed_at < NOW() - make_interval(days => $2)
                AND {tenant_predicate(3)}
                """,
                consumer_name,
                older_than_days,
                tenant_param(),
            )
            # Parse "DELETE N" to get count
            return int(result.split()[-1]) if result.startswith("DELETE") else 0
