"""Delivery reservations of the PostgreSQL saga log (#561).

A ``saga_delivery`` row with ``claimed_until`` set is a delivery being handled,
reserved until then; ``NULL`` means consumed for good (every row written
before #561). A delivery whose handler died is claimed again once its
reservation expired.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.core.storage._tenancy import write_tenant
from sagaz.core.storage.backends.postgresql._tenancy import acquire_scoped

# ON CONFLICT locks the existing row and re-checks the WHERE: of concurrent
# claims, only one takes a new or expired reservation.
_LEASE = (
    "INSERT INTO saga_delivery (tenant_id, participant, event_id, consumed_at, claimed_until)"
    " VALUES ($1, $2, $3, $4, $5)"
    " ON CONFLICT (tenant_id, participant, event_id) DO UPDATE SET"
    " consumed_at = EXCLUDED.consumed_at, claimed_until = EXCLUDED.claimed_until"
    " WHERE saga_delivery.claimed_until <= $4 RETURNING 1"
)
_FINISH = (
    "INSERT INTO saga_delivery (tenant_id, participant, event_id, consumed_at, claimed_until)"
    " VALUES ($1, $2, $3, $4, NULL)"
    " ON CONFLICT (tenant_id, participant, event_id) DO UPDATE SET"
    " consumed_at = EXCLUDED.consumed_at, claimed_until = NULL"
)


class PostgreSQLDeliveryMixin:
    _get_pool: Callable[[], Awaitable[Any]]  # provided by the store

    async def lease_delivery(self, participant: str, event_id: str, lease: timedelta) -> bool:
        now = datetime.now(UTC)
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            claimed = await conn.fetchval(
                _LEASE, write_tenant(), participant, event_id, now, now + lease
            )
        return claimed is not None

    async def finish_delivery(self, participant: str, event_id: str) -> None:
        pool = await self._get_pool()
        async with acquire_scoped(pool) as conn:
            await conn.execute(_FINISH, write_tenant(), participant, event_id, datetime.now(UTC))
