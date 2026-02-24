"""
Redis Outbox Storage using Redis Streams.

Provides high-performance outbox storage using Redis Streams
for reliable event delivery with consumer groups.
"""

import logging
import time
from datetime import UTC, datetime, timezone
from typing import Any

from sagaz.outbox.types import OutboxEvent, OutboxStatus
from sagaz.storage.core import (
    HealthCheckResult,
    HealthStatus,
    StorageStatistics,
    deserialize,
    serialize,
)
from sagaz.storage.interfaces import OutboxStorage, OutboxStorageError

logger = logging.getLogger(__name__)


class RedisOutboxStorage(OutboxStorage):
    """
    Redis-based outbox storage using Redis Streams.

    Uses Redis Streams for reliable event delivery:
    - XADD for inserting events
    - XREADGROUP for claiming batches (consumer groups)
    - XACK for acknowledging processed events

    Schema:
        {prefix}:events       - Main stream of pending events
        {prefix}:processing   - Hash of events being processed
        {prefix}:dlq          - Stream of dead-letter events
        {prefix}:meta:{id}    - Hash with full event metadata

    Usage:
        >>> storage = RedisOutboxStorage("redis://localhost:6379")
        >>> await storage.initialize()
        >>>
        >>> # Insert event
        >>> event = await storage.insert(OutboxEvent(...))
        >>>
        >>> # Claim events for processing
        >>> events = await storage.claim_batch("worker-1", batch_size=100)
        >>>
        >>> # Mark as sent
        >>> await storage.update_status(event.event_id, OutboxStatus.SENT)
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        prefix: str = "sagaz:outbox",
        consumer_group: str = "sagaz-workers",
        max_stream_length: int = 100000,
        event_ttl_seconds: int = 86400 * 7,  # 7 days
        **redis_kwargs,
    ):
        """
        Initialize Redis outbox storage.

        Args:
            redis_url: Redis connection URL
            prefix: Key prefix for all outbox keys
            consumer_group: Consumer group name for XREADGROUP
            max_stream_length: Maximum stream length (MAXLEN for XADD)
            event_ttl_seconds: TTL for event metadata hashes
            **redis_kwargs: Additional Redis connection options
        """
        self._redis_url = redis_url
        self._prefix = prefix
        self._consumer_group = consumer_group
        self._max_stream_length = max_stream_length
        self._event_ttl_seconds = event_ttl_seconds
        self._redis_kwargs = redis_kwargs

        self._redis = None
        self._initialized = False

        # Key names
        self._stream_key = f"{prefix}:events"
        self._dlq_key = f"{prefix}:dlq"
        self._processing_key = f"{prefix}:processing"

    async def initialize(self) -> None:
        """Initialize Redis connection and create consumer group."""
        if self._initialized:
            return

        try:
            import redis.asyncio as redis
        except ImportError:
            msg = "redis package required. Install with: pip install redis"
            raise ImportError(msg)

        self._redis = redis.from_url(self._redis_url, **self._redis_kwargs)
        assert self._redis is not None

        # Create consumer group if it doesn't exist
        try:
            await self._redis.xgroup_create(
                self._stream_key,
                self._consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(f"Created consumer group '{self._consumer_group}'")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            # Group already exists, that's fine

        self._initialized = True
        logger.info(f"Redis outbox storage initialized: {self._prefix}")

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        self._initialized = False

    def _meta_key(self, event_id: str) -> str:
        """Get metadata key for an event."""
        return f"{self._prefix}:meta:{event_id}"

    def _serialize_event(self, event: OutboxEvent) -> dict[str, str]:
        """Serialize event for Redis storage."""
        return {
            "event_id": event.event_id,
            "saga_id": event.saga_id,
            "aggregate_type": event.aggregate_type or "saga",
            "aggregate_id": event.aggregate_id or "",
            "event_type": event.event_type,
            "payload": serialize(event.payload),
            "headers": serialize(event.headers),
            "status": event.status.value,
            "retry_count": str(event.retry_count),
            "created_at": event.created_at.isoformat() if event.created_at else "",
            "claimed_at": event.claimed_at.isoformat() if event.claimed_at else "",
            "sent_at": event.sent_at.isoformat() if event.sent_at else "",
            "last_error": event.last_error or "",
            "worker_id": event.worker_id or "",
            "routing_key": event.routing_key or "",
            "partition_key": event.partition_key or "",
        }

    def _deserialize_event(self, data: dict[bytes | str, bytes | str]) -> OutboxEvent:
        """Deserialize event from Redis storage."""
        # Decode bytes to strings
        decoded = {}
        for k, v in data.items():
            key = k.decode() if isinstance(k, bytes) else k
            value = v.decode() if isinstance(v, bytes) else v
            decoded[key] = value

        def parse_datetime(s: str) -> datetime | None:
            if not s:
                return None
            return datetime.fromisoformat(s)

        return OutboxEvent(
            event_id=decoded.get("event_id", ""),
            saga_id=decoded.get("saga_id", ""),
            aggregate_type=decoded.get("aggregate_type", "saga"),
            aggregate_id=decoded.get("aggregate_id") or None,
            event_type=decoded.get("event_type", ""),
            payload=deserialize(decoded.get("payload", "{}")),
            headers=deserialize(decoded.get("headers", "{}")),
            status=OutboxStatus(decoded.get("status", "pending")),
            retry_count=int(decoded.get("retry_count", 0)),
            created_at=parse_datetime(decoded.get("created_at", "")) or datetime.now(UTC),
            claimed_at=parse_datetime(decoded.get("claimed_at", "")),
            sent_at=parse_datetime(decoded.get("sent_at", "")),
            last_error=decoded.get("last_error") or None,
            worker_id=decoded.get("worker_id") or None,
            routing_key=decoded.get("routing_key") or None,
            partition_key=decoded.get("partition_key") or None,
        )

    # ==========================================================================
    # Core Operations
    # ==========================================================================

    async def insert(
        self,
        event: OutboxEvent,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Insert event into Redis stream."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        # Store full metadata in hash
        meta_key = self._meta_key(event.event_id)
        event_data = self._serialize_event(event)

        async with self._redis.pipeline() as pipe:
            # Store metadata
            pipe.hset(meta_key, mapping=event_data)
            pipe.expire(meta_key, self._event_ttl_seconds)

            # Add to stream (minimal data for claiming)
            stream_data = {
                "event_id": event.event_id,
                "saga_id": event.saga_id,
                "event_type": event.event_type,
            }
            pipe.xadd(
                self._stream_key,
                stream_data,
                maxlen=self._max_stream_length,
            )

            await pipe.execute()

        logger.debug(f"Inserted outbox event: {event.event_id}")
        return event

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get event by ID from metadata hash."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        meta_key = self._meta_key(event_id)
        data = await self._redis.hgetall(meta_key)

        if not data:
            return None

        return self._deserialize_event(data)

    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Update event status."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        meta_key = self._meta_key(event_id)
        now = datetime.now(UTC).isoformat()

        updates = {"status": status.value}

        if status == OutboxStatus.SENT:
            updates["sent_at"] = now
        elif status == OutboxStatus.FAILED and error_message:
            updates["last_error"] = error_message

        await self._redis.hset(meta_key, mapping=updates)

        # If sent or dead letter, remove from processing set
        if status in (OutboxStatus.SENT, OutboxStatus.FAILED, OutboxStatus.DEAD_LETTER):
            await self._redis.hdel(self._processing_key, event_id)

        # Get updated event
        event = await self.get_by_id(event_id)
        if not event:
            msg = f"Event not found: {event_id}"
            raise OutboxStorageError(msg)

        return event

    # ==========================================================================
    # Batch Operations
    # ==========================================================================

    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """
        Claim a batch of pending events using XREADGROUP.

        Uses Redis consumer groups for reliable claiming.
        """
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        response = await self._read_from_stream(worker_id, batch_size)
        if not response:
            return []

        events = await self._process_claimed_messages(response, worker_id)

        if events:
            logger.debug(f"Worker {worker_id} claimed {len(events)} events")

        return events

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

    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """Get all events for a saga (requires scanning)."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        # This is expensive - scan all metadata keys
        events = []
        cursor = 0
        pattern = f"{self._prefix}:meta:*"

        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)

            for key in keys:
                data = await self._redis.hgetall(key)
                if data:
                    decoded_saga_id = (
                        data.get(b"saga_id", b"").decode()
                        if isinstance(data.get(b"saga_id"), bytes)
                        else data.get("saga_id", "")
                    )
                    if decoded_saga_id == saga_id:
                        events.append(self._deserialize_event(data))

            if cursor == 0:
                break

        return events

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

    # ==========================================================================
    # Statistics
    # ==========================================================================

    async def get_pending_count(self) -> int:
        """Get count of pending events."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        try:
            return await self._redis.xlen(self._stream_key)
        except Exception:
            return 0

    async def get_dead_letter_events(self, limit: int = 100) -> list[OutboxEvent]:
        """Get events in dead letter queue."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        events = []

        try:
            messages = await self._redis.xrange(self._dlq_key, count=limit)
            for _message_id, data in messages:
                event_id = (
                    data.get(b"event_id", b"").decode()
                    if isinstance(data.get(b"event_id"), bytes)
                    else data.get("event_id", "")
                )
                event = await self.get_by_id(event_id)
                if event:
                    events.append(event)
        except Exception as e:
            logger.warning(f"Error reading DLQ: {e}")

        return events

    async def health_check(self) -> HealthCheckResult:
        """Check Redis connection health."""
        if not self._initialized:
            try:
                await self.initialize()
            except Exception as e:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=0,
                    message=f"Failed to initialize: {e}",
                )

        start = time.perf_counter()

        try:
            assert self._redis is not None
            await self._redis.ping()
            stream_len = await self._redis.xlen(self._stream_key)
            elapsed_ms = (time.perf_counter() - start) * 1000

            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed_ms,
                message="OK",
                details={
                    "stream_length": stream_len,
                    "consumer_group": self._consumer_group,
                },
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=elapsed_ms,
                message=f"Redis error: {e}",
            )

    async def get_statistics(self) -> StorageStatistics:
        """Get storage statistics."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        pending = await self.get_pending_count()

        try:
            dlq_len = await self._redis.xlen(self._dlq_key)
        except Exception:
            dlq_len = 0

        return StorageStatistics(
            pending_records=pending,
            failed_records=dlq_len,
        )

    async def count(self) -> int:
        """Count total outbox events (pending + processed + dlq)."""
        # This is expensive, requires counting metakeys or stream lengths
        return await self.get_pending_count()

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
                    yield self._deserialize_event(data)
            if cursor == 0:
                break

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a record."""
        # Convert dict to OutboxEvent then insert
        event = OutboxEvent(
            event_id=str(record.get("event_id")),
            saga_id=record["saga_id"],
            event_type=record["event_type"],
            payload=record.get("payload", {}),
            status=OutboxStatus(record.get("status", "pending")),
        )
        await self.insert(event)

    # ==========================================================================
    # Context Manager
    # ==========================================================================

    async def __aenter__(self) -> "RedisOutboxStorage":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
