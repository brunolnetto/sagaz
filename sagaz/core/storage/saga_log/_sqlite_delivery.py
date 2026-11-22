"""Delivery reservations of the SQLite saga log (#561).

A ``saga_delivery`` row with ``claimed_until`` set is a delivery being handled,
reserved until then; ``NULL`` means consumed for good (every row written
before #561). A delivery whose handler died is claimed again once its
reservation expired.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sagaz.core.storage._tenancy import write_tenant

if TYPE_CHECKING:
    from aiosqlite import Connection

# Under the store's write lock: SQLite has one writer, so the claim is atomic.
_LEASE = (
    "INSERT INTO saga_delivery (tenant_id, participant, event_id, consumed_at, claimed_until)"
    " VALUES (?, ?, ?, ?, ?)"
    " ON CONFLICT (tenant_id, participant, event_id) DO UPDATE SET"
    " consumed_at = excluded.consumed_at, claimed_until = excluded.claimed_until"
    " WHERE saga_delivery.claimed_until <= ?"
)
_FINISH = (
    "INSERT INTO saga_delivery (tenant_id, participant, event_id, consumed_at, claimed_until)"
    " VALUES (?, ?, ?, ?, NULL)"
    " ON CONFLICT (tenant_id, participant, event_id) DO UPDATE SET"
    " consumed_at = excluded.consumed_at, claimed_until = NULL"
)


def _at(moment: datetime) -> str:
    # A fixed width, so reservation times compare as text.
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


async def migrate_deliveries(conn: Connection) -> None:
    """Add ``claimed_until`` to a ``saga_delivery`` table created before #561."""
    cursor = await conn.execute("PRAGMA table_info(saga_delivery)")
    if "claimed_until" not in {row[1] for row in await cursor.fetchall()}:
        await conn.execute("ALTER TABLE saga_delivery ADD COLUMN claimed_until TEXT")


class SQLiteDeliveryMixin:
    # Provided by the store.
    _lock: asyncio.Lock
    _connection: Callable[[], Awaitable[Any]]

    async def lease_delivery(self, participant: str, event_id: str, lease: timedelta) -> bool:
        conn = await self._connection()
        now = datetime.now(UTC)
        async with self._lock:
            cursor = await conn.execute(
                _LEASE,
                (write_tenant(), participant, event_id, _at(now), _at(now + lease), _at(now)),
            )
            await conn.commit()
        return bool(cursor.rowcount == 1)

    async def finish_delivery(self, participant: str, event_id: str) -> None:
        conn = await self._connection()
        async with self._lock:
            await conn.execute(
                _FINISH, (write_tenant(), participant, event_id, _at(datetime.now(UTC)))
            )
            await conn.commit()
