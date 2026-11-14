"""
Redis Outbox Storage using Redis Streams.

Provides high-performance outbox storage using Redis Streams
for reliable event delivery with consumer groups.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage.backends.redis._outbox_claiming import RedisOutboxClaimingMixin
from sagaz.core.storage.backends.redis._outbox_dlq import RedisOutboxDeadLetterMixin
from sagaz.core.storage.backends.redis._outbox_pending import RedisOutboxPendingCountMixin
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)
from sagaz.core.storage.backends.redis._outbox_status import RedisOutboxStatusUpdatesMixin
from sagaz.core.storage.backends.redis._outbox_transfer import RedisOutboxTransferMixin
from sagaz.core.storage.core import (
    HealthCheckResult,
    HealthStatus,
    StorageStatistics,
)
from sagaz.core.storage.interfaces import OutboxStorage, OutboxStorageError

logger = logging.getLogger(__name__)


class RedisOutboxStorage(
    RedisOutboxStatusUpdatesMixin,
    RedisOutboxClaimingMixin,
    RedisOutboxDeadLetterMixin,
    RedisOutboxPendingCountMixin,
    RedisOutboxTransferMixin,
    RedisOutboxSerializationMixin,
    OutboxStorage,
):
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

        self._redis: Any = None
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
            raise ImportError(msg) from None

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
            await self._redis.close()
            self._redis = None
        self._initialized = False

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
        event: OutboxEvent | None = None,
    ) -> OutboxEvent:
        """Update event status."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        meta_key = self._meta_key(event_id)
        now = datetime.now(UTC).isoformat()
        updates = await self._build_status_updates(event_id, status, error_message, event, now)

        await self._redis.hset(meta_key, mapping=updates)

        # The delivery is finished: ack it so the consumer group's pending list
        # only holds in-flight claims, then drop it from the processing hash.
        if status in (OutboxStatus.SENT, OutboxStatus.FAILED, OutboxStatus.DEAD_LETTER):
            message_id = await self._redis.hget(self._processing_key, event_id)
            if message_id:
                await self._redis.xack(self._stream_key, self._consumer_group, message_id)
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
    # Statistics
    # ==========================================================================

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

    # ==========================================================================
    # Context Manager
    # ==========================================================================

    async def __aenter__(self) -> "RedisOutboxStorage":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
