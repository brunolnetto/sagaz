"""
Dead-letter queue operations for ``RedisOutboxStorage``.

Dead-lettered events are found by scanning the event metadata hashes, since
Redis keeps no secondary index by status.
"""

from datetime import UTC, datetime, timedelta

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus, ReplayLoopError
from sagaz.core.storage.backends.redis._outbox_base import logger
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)


class RedisOutboxDeadLetterMixin(RedisOutboxSerializationMixin):
    """List, replay and purge dead-letter events."""

    async def get_dead_letter_events(self, limit: int = 100) -> list[OutboxEvent]:
        """Get events in dead letter queue."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        events = []
        pattern = f"{self._prefix}:meta:*"
        cursor = 0
        try:
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                for key in keys:
                    data = await self._redis.hgetall(key)
                    if not data:
                        continue
                    event = self._deserialize_event(data)
                    if event.status == OutboxStatus.DEAD_LETTER:
                        events.append(event)
                        if len(events) >= limit:
                            return events
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(f"Error reading DLQ: {e}")
        return events

    async def requeue_dead_letter_event(self, event_id: str, force: bool = False) -> OutboxEvent:
        """Move a DLQ event back to PENDING."""
        if not self._initialized:
            await self.initialize()
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
        event.status = OutboxStatus.PENDING
        event.retry_count = 0
        event.worker_id = None
        event.claimed_at = None
        event.dead_letter_at = None
        event.dead_letter_reason = None

        assert self._redis is not None
        await self._redis.xadd(
            self._stream_key,
            {"event_id": event.event_id, "saga_id": event.saga_id, "event_type": event.event_type},
            maxlen=self._max_stream_length,
        )
        return await self.update_status(event_id, OutboxStatus.PENDING, event=event)

    async def purge_dead_letter_events(self, older_than: timedelta | None = None) -> int:
        """Permanently remove DLQ events."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        now = datetime.now(UTC)
        purged = 0
        pattern = f"{self._prefix}:meta:*"
        cursor = 0

        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                data = await self._redis.hgetall(key)
                if not data:
                    continue
                event = self._deserialize_event(data)
                if self._should_purge_dead_letter(event, older_than, now):
                    await self._redis.delete(key)
                    purged += 1
            if cursor == 0:
                break

        return purged

    @staticmethod
    def _should_purge_dead_letter(
        event: OutboxEvent, older_than: timedelta | None, now: datetime
    ) -> bool:
        if event.status != OutboxStatus.DEAD_LETTER:
            return False
        if older_than is None:
            return True
        if event.dead_letter_at is None:
            return False
        return (now - event.dead_letter_at) >= older_than
