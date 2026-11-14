"""
Counting, export and import of outbox events for ``RedisOutboxStorage``.

Used by storage transfer/migration tooling to move events between backends.
"""

from typing import Any

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage._outbox_tenancy import resolve_event_tenant
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)
from sagaz.core.storage.interfaces import OutboxStorageError
from sagaz.core.tenant import DEFAULT_TENANT, tenant_scope


class RedisOutboxTransferMixin(RedisOutboxSerializationMixin):
    """``count``/``export_all``/``import_record`` over the metadata hashes."""

    async def count(self) -> int:
        """Count the retained outbox event metadata records of the current tenant(s)."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        return sum(await self._per_tenant(self._count_scoped))

    async def _count_scoped(self) -> int:
        total = 0
        cursor = 0
        pattern = self._meta_pattern()
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=500)
            total += len(keys)
            if cursor == 0:
                break
        return total

    async def export_all(self):
        """Export the events of the current tenant(s)."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        # Patterns are built per tenant: an async generator must not enter a
        # tenant scope, as the scope would leak to the caller between yields.
        for tenant in await self._scope_tenants():
            pattern = self._meta_pattern(tenant)
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                for key in keys:
                    data = await self._redis.hgetall(key)
                    if data:
                        yield self._deserialize_event(data).to_dict()
                if cursor == 0:
                    break

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import an event atomically without overwriting destination state."""
        event = OutboxEvent.from_dict(record)

        if not self._initialized:
            await self.initialize()

        assert self._redis is not None
        with tenant_scope(resolve_event_tenant(event)):
            await self._import_scoped(event)

    async def _import_scoped(self, event: OutboxEvent) -> None:
        from redis.exceptions import WatchError

        meta_key = self._meta_key(event.event_id)
        stream_key = self._scoped_stream_key()
        await self._ensure_group(stream_key)
        event_data = self._serialize_event(event)

        while True:
            async with self._redis.pipeline(transaction=True) as pipe:
                try:
                    # WATCH detects changes made by workers or other importers
                    # between reading metadata and committing the import.
                    await pipe.watch(meta_key)
                    existing_data = await pipe.hgetall(meta_key)

                    if existing_data:
                        existing = self._deserialize_event(existing_data)
                        if existing != event:
                            msg = (
                                f"Outbox event {event.event_id} already exists with different state"
                            )
                            raise OutboxStorageError(msg)

                        await pipe.unwatch()
                        return

                    pipe.multi()
                    if event.tenant_id != DEFAULT_TENANT:
                        pipe.sadd(self._tenants_key, event.tenant_id)
                    pipe.hset(meta_key, mapping=event_data)
                    pipe.expire(meta_key, self._event_ttl_seconds)

                    if event.status in (
                        OutboxStatus.PENDING,
                        OutboxStatus.CLAIMED,
                    ):
                        pipe.xadd(
                            stream_key,
                            {
                                "event_id": event.event_id,
                                "saga_id": event.saga_id,
                                "event_type": event.event_type,
                            },
                            maxlen=self._max_stream_length,
                        )

                    await pipe.execute()
                    return

                except WatchError:
                    # Metadata changed concurrently. Re-read and compare
                    # instead of applying a potentially stale snapshot.
                    continue
