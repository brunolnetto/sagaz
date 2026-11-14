"""
Consumer-group claiming and stuck-event recovery for ``RedisOutboxStorage``.

Claims are made with XREADGROUP; events whose delivery has been pending for
too long are found through XPENDING and re-claimed with XCLAIM. Each claimed
message is processed in the scope of the tenant whose stream it came from.
"""

from datetime import UTC, datetime

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis._outbox_base import logger
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)
from sagaz.core.tenant import tenant_scope


class RedisOutboxClaimingMixin(RedisOutboxSerializationMixin):
    """Claim helpers for ``claim_batch`` plus stuck-event recovery."""

    async def _read_from_stream(
        self, worker_id: str, batch_size: int, streams: dict[str, str] | None = None
    ):
        """Read messages from the consumer group of each stream in ``streams``."""
        assert self._redis is not None
        streams = streams or {self._scoped_stream_key(): ""}
        try:
            for stream_key in streams:
                await self._ensure_group(stream_key)
            return await self._redis.xreadgroup(
                groupname=self._consumer_group,
                consumername=worker_id,
                streams=dict.fromkeys(streams, ">"),
                count=batch_size,
                block=1000,
            )
        except Exception as e:
            logger.warning(f"Error reading from stream: {e}")
            return None

    async def _process_claimed_messages(
        self, response: list, worker_id: str, streams: dict[str, str] | None = None
    ) -> list[OutboxEvent]:
        """Process messages from stream response.

        ``streams`` maps each stream key to its tenant; messages of unmapped
        streams are processed in the current scope.
        """
        events = []
        now = datetime.now(UTC)

        for stream_name, messages in response:
            tenant = (streams or {}).get(self._decode(stream_name))
            for message_id, message_data in messages:
                event = await self._claim_in_tenant(
                    tenant, message_id, message_data, worker_id, now
                )
                if event:
                    events.append(event)

        return events

    @staticmethod
    def _decode(value) -> str:
        return value.decode() if isinstance(value, bytes) else value

    async def _claim_in_tenant(
        self, tenant: str | None, message_id, message_data: dict, worker_id: str, now: datetime
    ) -> OutboxEvent | None:
        if not tenant:
            return await self._claim_single_message(message_id, message_data, worker_id, now)
        with tenant_scope(tenant):
            return await self._claim_single_message(message_id, message_data, worker_id, now)

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
            await self._redis.xack(self._scoped_stream_key(), self._consumer_group, message_id)
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
        await self._redis.hset(self._scoped_processing_key(), event_id, msg_id_str)

    # ==========================================================================
    # Stuck Event Recovery
    # ==========================================================================

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """Get events of the current tenant(s) that appear to be stuck."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        per_tenant = await self._per_tenant(
            lambda: self._stuck_events_scoped(claimed_older_than_seconds)
        )
        return [event for events in per_tenant for event in events]

    async def _stuck_events_scoped(self, claimed_older_than_seconds: float) -> list[OutboxEvent]:
        # Check pending entries in consumer group
        try:
            pending = await self._redis.xpending_range(
                self._scoped_stream_key(),
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
        """Release stuck events of the current tenant(s) back to pending."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        released = sum(
            await self._per_tenant(lambda: self._release_stuck_scoped(claimed_older_than_seconds))
        )
        if released:
            logger.info(f"Released {released} stuck events")
        return released

    async def _release_stuck_scoped(self, claimed_older_than_seconds: float) -> int:
        # Get pending entries
        try:
            pending = await self._redis.xpending_range(
                self._scoped_stream_key(),
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
                        self._scoped_stream_key(),
                        self._consumer_group,
                        "recovery-worker",
                        min_idle_time=threshold_ms,
                        message_ids=[message_id],
                    )
                    released += 1
                except Exception as e:
                    logger.warning(f"Failed to release stuck event: {e}")

        return released
