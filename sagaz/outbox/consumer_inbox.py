"""
Consumer-side deduplication using inbox pattern.

Ensures exactly-once processing despite at-least-once delivery.
"""
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

# Optional prometheus metrics
try:
    from prometheus_client import Counter, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # No-op fallbacks
    class _NoOpMetric:
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    Counter = lambda *args, **kwargs: _NoOpMetric()
    Histogram = lambda *args, **kwargs: _NoOpMetric()

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Metrics (no-op if prometheus not installed)
INBOX_PROCESSED = Counter(
    "consumer_inbox_processed_total",
    "Total events processed",
    ["consumer_name", "event_type"]
)
INBOX_DUPLICATES = Counter(
    "consumer_inbox_duplicates_total",
    "Total duplicate events skipped",
    ["consumer_name", "event_type"]
)
INBOX_PROCESSING_DURATION = Histogram(
    "consumer_inbox_processing_duration_seconds",
    "Time to process event",
    ["consumer_name", "event_type"]
)


class ConsumerInbox:
    """
    Idempotent message consumer with inbox deduplication.
    
    Usage:
        inbox = ConsumerInbox(storage, "order-service")
        
        await inbox.process_idempotent(
            event_id="evt-123",
            source_topic="orders",
            event_type="OrderCreated",
            payload={"order_id": "ord-456"},
            handler=process_order
        )
    """

    def __init__(self, storage, consumer_name: str):
        self.storage = storage
        self.consumer_name = consumer_name

    async def process_idempotent(
        self,
        event_id: str,
        source_topic: str,
        event_type: str,
        payload: dict,
        handler: Callable[[dict], Awaitable[T]]
    ) -> T | None:
        """
        Process message idempotently.
        
        Returns:
            Handler result if processed, None if duplicate
        """
        start_time = datetime.now(UTC)

        # Try to insert (atomic dedup check)
        is_duplicate = await self.storage.check_and_insert_inbox(
            event_id=event_id,
            consumer_name=self.consumer_name,
            source_topic=source_topic,
            event_type=event_type,
            payload=payload
        )

        if is_duplicate:
            # Already processed - skip
            INBOX_DUPLICATES.labels(
                consumer_name=self.consumer_name,
                event_type=event_type
            ).inc()

            logger.info(f"Duplicate message: {event_id}, skipping")
            return None

        # New message - execute handler
        try:
            result = await handler(payload)

            # Update duration
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            await self.storage.update_inbox_duration(event_id, duration_ms)

            INBOX_PROCESSED.labels(
                consumer_name=self.consumer_name,
                event_type=event_type
            ).inc()

            logger.info(f"Processed event: {event_id} ({duration_ms}ms)")
            return result

        except Exception as exc:
            logger.error(f"Failed to process: {event_id}: {exc}", exc_info=True)
            raise

    async def cleanup_old_entries(self, older_than_days: int = 7) -> int:
        """Delete old inbox entries."""
        deleted = await self.storage.cleanup_inbox(
            consumer_name=self.consumer_name,
            older_than_days=older_than_days
        )

        logger.info(f"Cleaned up {deleted} old inbox entries")
        return deleted
