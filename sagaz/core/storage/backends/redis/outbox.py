"""
Redis Outbox Storage using Redis Streams.

Provides high-performance outbox storage using Redis Streams
for reliable event delivery with consumer groups.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus
from sagaz.core.storage._outbox_tenancy import resolve_event_tenant
from sagaz.core.storage.backends.redis._outbox_claiming import RedisOutboxClaimingMixin
from sagaz.core.storage.backends.redis._outbox_dlq import RedisOutboxDeadLetterMixin
from sagaz.core.storage.backends.redis._outbox_serialization import (
    RedisOutboxSerializationMixin,
)
from sagaz.core.storage.backends.redis._outbox_stats import RedisOutboxStatisticsMixin
from sagaz.core.storage.backends.redis._outbox_status import RedisOutboxStatusUpdatesMixin
from sagaz.core.storage.backends.redis._outbox_transfer import RedisOutboxTransferMixin
from sagaz.core.storage.interfaces import OutboxStorage, OutboxStorageError
from sagaz.core.tenant import DEFAULT_TENANT, tenant_scope

logger = logging.getLogger(__name__)


class RedisOutboxStorage(
    RedisOutboxStatisticsMixin,
    RedisOutboxStatusUpdatesMixin,
    RedisOutboxClaimingMixin,
    RedisOutboxDeadLetterMixin,
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

    Schema (per tenant, under ``{tp}`` = ``{prefix}`` for the default tenant
    and ``sagaz:{tenant_id}:{prefix}`` otherwise, see ADR-020):
        {tp}:events           - Main stream of pending events
        {tp}:processing       - Hash of events being processed
        {tp}:dlq              - Stream of dead-letter events
        {tp}:meta:{id}        - Hash with full event metadata
        {prefix}:tenants      - Set of non-default tenants with outbox data

    In the system scope (the outbox worker) ``claim_batch`` reads every
    tenant's stream and the other operations span every tenant.

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

        # Key names of the default tenant (see _outbox_tenancy for the others)
        self._ready_groups: set[str] = set()
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

        # Create the default tenant's consumer group if it doesn't exist
        self._ready_groups.clear()
        await self._ensure_group(self._stream_key)

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
        """Insert event into its tenant's Redis stream."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        tenant_id = resolve_event_tenant(event)
        with tenant_scope(tenant_id):
            await self._insert_scoped(event)
        logger.debug(f"Inserted outbox event: {event.event_id}")
        return event

    async def _insert_scoped(self, event: OutboxEvent) -> None:
        stream_key = self._scoped_stream_key()
        await self._ensure_group(stream_key)

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
                stream_key,
                stream_data,
                maxlen=self._max_stream_length,
            )
            if event.tenant_id != DEFAULT_TENANT:
                pipe.sadd(self._tenants_key, event.tenant_id)

            await pipe.execute()

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get an event of the current tenant (any tenant in the system scope)."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        async with self._event_tenant_scope(event_id) as tenant:
            if tenant is None:
                return None
            data = await self._redis.hgetall(self._meta_key(event_id))

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
        """Update the status of an event of the current tenant."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        async with self._event_tenant_scope(event_id, event.tenant_id if event else None) as t:
            if t is None:
                msg = f"Event not found: {event_id}"
                raise OutboxStorageError(msg)
            return await self._update_status_scoped(event_id, status, error_message, event)

    async def _update_status_scoped(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None,
        event: OutboxEvent | None,
    ) -> OutboxEvent:
        meta_key = self._meta_key(event_id)
        if not await self._redis.exists(meta_key):
            # Never create a partial hash for an unknown (or other tenant's) event.
            msg = f"Event not found: {event_id}"
            raise OutboxStorageError(msg)
        now = datetime.now(UTC).isoformat()
        updates = await self._build_status_updates(event_id, status, error_message, event, now)

        await self._redis.hset(meta_key, mapping=updates)

        # If sent or dead letter, remove from processing set
        if status in (OutboxStatus.SENT, OutboxStatus.FAILED, OutboxStatus.DEAD_LETTER):
            await self._redis.hdel(self._scoped_processing_key(), event_id)

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

        Uses Redis consumer groups for reliable claiming. In the system scope
        every tenant's stream is read in one call (up to ``batch_size`` events
        per stream).
        """
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        streams = {
            self._scoped_stream_key(tenant): tenant for tenant in await self._scope_tenants()
        }
        response = await self._read_from_stream(worker_id, batch_size, streams)
        if not response:
            return []

        events = await self._process_claimed_messages(response, worker_id, streams)

        if events:
            logger.debug(f"Worker {worker_id} claimed {len(events)} events")

        return events

    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """Get all events of the current tenant(s) for a saga (requires scanning)."""
        if not self._initialized:
            await self.initialize()
        assert self._redis is not None

        per_tenant = await self._per_tenant(lambda: self._events_by_saga_scoped(saga_id))
        return [event for events in per_tenant for event in events]

    async def _events_by_saga_scoped(self, saga_id: str) -> list[OutboxEvent]:
        # This is expensive - scan all metadata keys
        events = []
        cursor = 0
        pattern = self._meta_pattern()

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
    # Context Manager
    # ==========================================================================

    async def __aenter__(self) -> "RedisOutboxStorage":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
