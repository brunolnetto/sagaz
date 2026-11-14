"""
Counting, export and import of outbox events for ``RedisOutboxStorage``.

Used by storage transfer/migration tooling to move events between backends.
"""

from typing import Any

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)
from sagaz.core.storage.interfaces import OutboxStorageError


class RedisOutboxTransferMixin(RedisOutboxSerializationMixin):
    """``count``/``export_all``/``import_record`` over the metadata hashes."""

    async def count(self) -> int:
        """Count all retained outbox event metadata records."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        total = 0
        cursor = 0
        pattern = f"{self._prefix}:meta:*"
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=500)
            total += len(keys)
            if cursor == 0:
                break
        return total

    async def export_all(self):
        """Export all events."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        pattern = f"{self._prefix}:meta:*"
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
        from redis.exceptions import WatchError

        event = OutboxEvent.from_dict(record)

        if not self._initialized:
            await self.initialize()

        assert self._redis is not None
        meta_key = self._meta_key(event.event_id)
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
                    pipe.hset(meta_key, mapping=event_data)
                    pipe.expire(meta_key, self._event_ttl_seconds)

                    if event.status in (
                        OutboxStatus.PENDING,
                        OutboxStatus.CLAIMED,
                    ):
                        pipe.xadd(
                            self._stream_key,
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
