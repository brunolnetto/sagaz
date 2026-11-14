"""
Consumer-group claiming and stuck-event recovery for ``RedisOutboxStorage``.

Claims are made with XREADGROUP; events whose delivery has been pending for
too long are found through XPENDING and re-claimed with XCLAIM.
"""

from datetime import UTC, datetime

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis._outbox_base import logger
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)


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

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """Get events that appear to be stuck."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        # Check pending entries in consumer group
        try:
            pending = await self._redis.xpending_range(
                self._stream_key,
                self._consumer_group,
                min="-",
                max="+",
                count=1000,
            )
        except Exception as e:
            logger.warning(f"Error getting pending entries: {e}")
            return []

        stuck = []
        threshold_ms = claimed_older_than_seconds * 1000

        for entry in pending:
            idle_time = entry.get("time_since_delivered", 0)
            if idle_time > threshold_ms:
                event_id = (
                    entry.get("message_id", b"").decode()
                    if isinstance(entry.get("message_id"), bytes)
                    else entry.get("message_id", "")
                )
                event = await self.get_by_id(event_id)
                if event:
                    stuck.append(event)

        return stuck

    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:
        """Release stuck events back to pending."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        # Get pending entries
        try:
            pending = await self._redis.xpending_range(
                self._stream_key,
                self._consumer_group,
                min="-",
                max="+",
                count=1000,
            )
        except Exception:
            return 0

        released = 0
        threshold_ms = int(claimed_older_than_seconds * 1000)

        for entry in pending:
            idle_time = entry.get("time_since_delivered", 0)
            if idle_time > threshold_ms:
                message_id = entry.get("message_id")

                # Claim the message for ourselves and re-add to stream
                try:
                    await self._redis.xclaim(
                        self._stream_key,
                        self._consumer_group,
                        "recovery-worker",
                        min_idle_time=threshold_ms,
                        message_ids=[message_id],
                    )
                    released += 1
                except Exception as e:
                    logger.warning(f"Failed to release stuck event: {e}")

        if released:
            logger.info(f"Released {released} stuck events")

        return released
