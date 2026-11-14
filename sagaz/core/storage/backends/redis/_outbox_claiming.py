"""
Consumer-group claiming and stuck-event recovery for ``RedisOutboxStorage``.

Claims are made with XREADGROUP. Deliveries pending for too long are found
through XPENDING (filtered by idle time) and mapped back to their events via
the processing hash; recovery acks the stale delivery and re-adds the event to
the stream so another consumer picks it up.
"""

from datetime import UTC, datetime

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis._outbox_base import logger
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)

# Entries fetched per XPENDING call while scanning for stuck deliveries.
_PENDING_PAGE_SIZE = 1000


class RedisOutboxClaimingMixin(RedisOutboxSerializationMixin):
    """Claim helpers for ``claim_batch`` plus stuck-event recovery."""

    async def _read_from_stream(self, worker_id: str, batch_size: int):
        """Read messages from consumer group stream."""
        assert self._redis is not None
        try:
            return await self._redis.xreadgroup(
                groupname=self._consumer_group,
                consumername=worker_id,
                streams={self._stream_key: ">"},
                count=batch_size,
                block=1000,
            )
        except Exception as e:
            logger.warning(f"Error reading from stream: {e}")
            return None

    async def _process_claimed_messages(self, response: list, worker_id: str) -> list[OutboxEvent]:
        """Process messages from stream response."""
        events = []
        now = datetime.now(UTC)

        for _stream_name, messages in response:
            for message_id, message_data in messages:
                event = await self._claim_single_message(message_id, message_data, worker_id, now)
                if event:
                    events.append(event)

        return events

    async def _claim_single_message(
        self, message_id, message_data: dict, worker_id: str, now: datetime
    ) -> OutboxEvent | None:
        """Claim and update a single message. Returns event or None."""
        event_id = self._extract_event_id(message_data)
        if not event_id:
            return None

        event = await self.get_by_id(event_id)
        if not event:
            # Acknowledge orphaned message
            assert self._redis is not None
            await self._redis.xack(self._stream_key, self._consumer_group, message_id)
            return None

        # Update claim metadata
        await self._update_claim_metadata(event_id, message_id, worker_id, now)

        event.status = OutboxStatus.CLAIMED
        event.claimed_at = now
        event.worker_id = worker_id
        return event

    def _extract_event_id(self, message_data: dict) -> str:
        """Extract event_id from message data (handles bytes/str)."""
        raw = message_data.get(b"event_id") or message_data.get("event_id", "")
        if isinstance(raw, bytes):
            return raw.decode()
        return raw or ""

    async def _update_claim_metadata(
        self, event_id: str, message_id, worker_id: str, now: datetime
    ) -> None:
        """Update Redis with claim information."""
        assert self._redis is not None
        meta_key = self._meta_key(event_id)
        await self._redis.hset(
            meta_key,
            mapping={
                "status": OutboxStatus.CLAIMED.value,
                "claimed_at": now.isoformat(),
                "worker_id": worker_id,
            },
        )

        msg_id_str = message_id.decode() if isinstance(message_id, bytes) else message_id
        assert self._redis is not None
        await self._redis.hset(self._processing_key, event_id, msg_id_str)

    # ==========================================================================
    # Stuck Event Recovery
    # ==========================================================================

    @staticmethod
    def _to_str(value: bytes | str) -> str:
        return value.decode() if isinstance(value, bytes) else value

    async def _idle_pending_message_ids(self, min_idle_ms: int) -> list[str]:
        """Stream ids of every delivered-but-unacked message idle >= ``min_idle_ms``."""
        assert self._redis is not None
        message_ids: list[str] = []
        start = "-"
        while True:
            page = await self._redis.xpending_range(
                self._stream_key,
                self._consumer_group,
                min=start,
                max="+",
                count=_PENDING_PAGE_SIZE,
                idle=min_idle_ms,
            )
            message_ids.extend(self._to_str(entry["message_id"]) for entry in page)
            if len(page) < _PENDING_PAGE_SIZE:
                return message_ids
            # Exclusive range start: continue after the last id of this page.
            start = f"({message_ids[-1]}"

    async def _find_stuck_claims(
        self, claimed_older_than_seconds: float
    ) -> list[tuple[str, OutboxEvent]]:
        """Return ``(stream message id, event)`` for claims idle past the threshold.

        XPENDING reports stream message ids, not event ids; the processing hash
        (``event_id -> message id``, written on claim) maps them back. Only
        events still in CLAIMED status are stuck.
        """
        assert self._redis is not None
        # Redis rejects a negative IDLE, so clamp the threshold at zero.
        min_idle_ms = max(0, int(claimed_older_than_seconds * 1000))
        try:
            message_ids = await self._idle_pending_message_ids(min_idle_ms)
            if not message_ids:
                return []
            in_flight = await self._redis.hgetall(self._processing_key)
        except Exception as e:
            logger.warning(f"Error getting pending entries: {e}")
            return []

        event_ids = {self._to_str(msg): self._to_str(eid) for eid, msg in in_flight.items()}
        stuck = []
        for message_id in message_ids:
            event_id = event_ids.get(message_id)
            event = await self.get_by_id(event_id) if event_id else None
            if event and event.status == OutboxStatus.CLAIMED:
                stuck.append((message_id, event))
        return stuck

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """Get events claimed longer than ``claimed_older_than_seconds`` ago."""
        if not self._initialized:
            await self.initialize()
        stuck = await self._find_stuck_claims(claimed_older_than_seconds)
        return [event for _message_id, event in stuck]

    async def _requeue_stuck_claim(self, message_id: str, event: OutboxEvent) -> bool:
        """Move one stuck claim back to PENDING and make it deliverable again.

        Acks the stale delivery and appends a fresh stream entry so a consumer
        reading new messages (``>``) picks the event up. The metadata hash is
        WATCHed, so a claim that completes concurrently is left alone.
        """
        from redis.exceptions import WatchError

        assert self._redis is not None
        meta_key = self._meta_key(event.event_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(meta_key)
                status = await pipe.hget(meta_key, "status")
                if status is None or self._to_str(status) != OutboxStatus.CLAIMED.value:
                    await pipe.unwatch()
                    return False
                pipe.multi()
                pipe.xack(self._stream_key, self._consumer_group, message_id)
                pipe.hdel(self._processing_key, event.event_id)
                pipe.hset(
                    meta_key,
                    mapping={
                        "status": OutboxStatus.PENDING.value,
                        "claimed_at": "",
                        "worker_id": "",
                    },
                )
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
                return True
            except WatchError:
                return False

    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:
        """Release stuck events back to PENDING and re-queue them for delivery."""
        if not self._initialized:
            await self.initialize()

        released = 0
        for message_id, event in await self._find_stuck_claims(claimed_older_than_seconds):
            try:
                if await self._requeue_stuck_claim(message_id, event):
                    released += 1
            except Exception as e:
                logger.warning(f"Failed to release stuck event {event.event_id}: {e}")

        if released:
            logger.info(f"Released {released} stuck events")

        return released
