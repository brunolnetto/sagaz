"""
Outbox Worker - Background processor for outbox events.

Polls the outbox for pending events and publishes them to the message broker.
Handles retries, dead-letter queue, and graceful shutdown.

Usage:
    >>> from sagaz.outbox import OutboxWorker, InMemoryOutboxStorage, InMemoryBroker
    >>>
    >>> storage = InMemoryOutboxStorage()
    >>> broker = InMemoryBroker()
    >>> await broker.connect()
    >>>
    >>> worker = OutboxWorker(storage, broker)
    >>> await worker.start()  # Runs until stopped
    >>> # or
    >>> await worker.process_batch()  # Process one batch
"""

import asyncio
import logging
import os
import signal
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

from sagaz.outbox.brokers.base import BrokerError, MessageBroker
from sagaz.outbox.state_machine import OutboxStateMachine
from sagaz.outbox.storage.base import OutboxStorage
from sagaz.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================================
# Prometheus Metrics (optional - gracefully degrade if not installed)
# ============================================================================

try:
    from prometheus_client import Counter, Gauge, Histogram

    PROMETHEUS_AVAILABLE = True

    # Counters
    OUTBOX_BATCH_PROCESSED = Counter(
        "outbox_batch_processed_total",
        "Total batches processed by outbox worker",
        ["worker_id"],
    )

    OUTBOX_PUBLISHED_EVENTS = Counter(
        "outbox_published_events_total",
        "Total events successfully published",
        ["worker_id", "event_type"],
    )

    OUTBOX_FAILED_EVENTS = Counter(
        "outbox_failed_events_total",
        "Total events that failed to publish",
        ["worker_id", "event_type"],
    )

    OUTBOX_DEAD_LETTER_EVENTS = Counter(
        "outbox_dead_letter_events_total",
        "Total events moved to dead letter queue",
        ["worker_id", "event_type"],
    )

    OUTBOX_RETRY_ATTEMPTS = Counter(
        "outbox_retry_attempts_total",
        "Total retry attempts",
        ["worker_id"],
    )

    # Gauges
    OUTBOX_PENDING_EVENTS = Gauge(
        "outbox_pending_events_total",
        "Current number of pending events in outbox",
    )

    OUTBOX_PROCESSING_EVENTS = Gauge(
        "outbox_processing_events_total",
        "Current number of events being processed",
        ["worker_id"],
    )

    OUTBOX_BATCH_SIZE = Gauge(
        "outbox_batch_size",
        "Size of last processed batch",
        ["worker_id"],
    )

    OUTBOX_EVENTS_BY_STATE = Gauge(
        "outbox_events_by_state",
        "Number of events per state",
        ["state"],
    )

    # Histograms
    OUTBOX_PUBLISH_DURATION = Histogram(
        "outbox_publish_duration_seconds",
        "Time to publish an event to the broker",
        ["worker_id", "event_type"],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0],
    )

except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.debug("prometheus-client not installed, metrics disabled")


class OutboxWorker:
    """
    Background worker that processes outbox events.

    Features:
        - Batch processing for efficiency
        - Parallel publish within batches
        - Exponential backoff on failures
        - Graceful shutdown on SIGTERM/SIGINT
        - Stuck event recovery
        - Dead letter queue handling

    Usage:
        >>> worker = OutboxWorker(storage, broker, config)
        >>>
        >>> # Run continuously
        >>> await worker.start()
        >>>
        >>> # Or process manually
        >>> processed = await worker.process_batch()
        >>> print(f"Processed {processed} events")

    Lifecycle:
        1. Claim batch of PENDING events (with SKIP LOCKED)
        2. Publish each event to broker in parallel
        3. Mark successful events as SENT
        4. Mark failed events as FAILED (retry later)
        5. Move exceeded-retry events to DEAD_LETTER
        6. Sleep and repeat
    """

    def __init__(
        self,
        storage: OutboxStorage,
        broker: MessageBroker,
        config: OutboxConfig | None = None,
        worker_id: str | None = None,
        on_event_published: Callable[[OutboxEvent], Awaitable[None]] | None = None,
        on_event_failed: Callable[[OutboxEvent, Exception], Awaitable[None]] | None = None,
    ):
        """
        Initialize the outbox worker.

        Args:
            storage: Outbox storage implementation
            broker: Message broker implementation
            config: Worker configuration
            worker_id: Unique ID for this worker (auto-generated if not provided)
            on_event_published: Callback when event is published successfully
            on_event_failed: Callback when event fails to publish
        """
        self.storage = storage
        self.broker = broker
        self.config = config or OutboxConfig()
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

        self._state_machine = OutboxStateMachine(max_retries=self.config.max_retries)
        self._running = False
        self._shutdown_event = asyncio.Event()

        self._on_event_published = on_event_published
        self._on_event_failed = on_event_failed

        # Metrics
        self._events_processed = 0
        self._events_failed = 0
        self._events_dead_lettered = 0

    async def start(self) -> None:
        """
        Start the worker loop.

        Runs continuously until stop() is called or shutdown signal received.
        """
        self._running = True
        self._shutdown_event.clear()

        logger.info(f"Outbox worker {self.worker_id} starting")
        self._setup_signal_handlers()

        try:
            await self._run_processing_loop()
        finally:
            self._running = False
            logger.info(f"Outbox worker {self.worker_id} stopped")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._handle_shutdown)
            except NotImplementedError:  # pragma: no cover
                pass  # Windows doesn't support add_signal_handler

    async def _run_processing_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            should_break = await self._process_iteration()
            if should_break:
                break

    async def _process_iteration(self) -> bool:
        """Process one iteration of the loop. Returns True if loop should break."""
        try:
            # Update pending events gauge
            if PROMETHEUS_AVAILABLE:
                try:
                    pending_count = await self.storage.get_pending_count()
                    OUTBOX_PENDING_EVENTS.set(pending_count)
                except Exception:
                    pass  # Ignore errors when getting pending count

            processed = await self.process_batch()
            if processed == 0:
                await self._wait_for_next_poll()
            return False
        except TimeoutError:
            return False  # Normal timeout, continue loop
        except asyncio.CancelledError:  # pragma: no cover
            logger.info(f"Worker {self.worker_id} cancelled")
            return True
        except Exception as e:  # pragma: no cover
            logger.error(f"Worker {self.worker_id} error: {e}")
            await asyncio.sleep(self.config.poll_interval_seconds)
            return False

    async def _wait_for_next_poll(self) -> None:
        """Wait for shutdown or poll interval."""
        await asyncio.wait_for(
            self._shutdown_event.wait(), timeout=self.config.poll_interval_seconds
        )

    async def stop(self) -> None:
        """Stop the worker gracefully."""
        logger.info(f"Stopping worker {self.worker_id}")
        self._running = False
        self._shutdown_event.set()

    def _handle_shutdown(self) -> None:
        """Handle shutdown signal."""
        logger.info(f"Shutdown signal received for worker {self.worker_id}")
        # Store reference to prevent garbage collection
        self._shutdown_task = asyncio.create_task(self.stop())

    async def process_batch(self) -> int:
        """
        Process a single batch of events.

        Returns:
            Number of events processed
        """
        # Claim batch of events
        events = await self.storage.claim_batch(
            worker_id=self.worker_id,
            batch_size=self.config.batch_size,
        )

        if not events:  # pragma: no cover
            return 0

        batch_size = len(events)
        logger.debug(f"Worker {self.worker_id} claimed {batch_size} events")

        # Record Prometheus metrics
        if PROMETHEUS_AVAILABLE:
            OUTBOX_BATCH_SIZE.labels(worker_id=self.worker_id).set(batch_size)
            OUTBOX_PROCESSING_EVENTS.labels(worker_id=self.worker_id).set(batch_size)

        # Process events in parallel
        tasks = [self._process_event(event) for event in events]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes and failures
        processed = 0
        for event, result in zip(events, results, strict=False):
            if isinstance(result, Exception):  # pragma: no cover
                logger.error(f"Failed to process event {event.event_id}: {result}")
            else:
                processed += 1

        # Record batch completion
        if PROMETHEUS_AVAILABLE:
            OUTBOX_BATCH_PROCESSED.labels(worker_id=self.worker_id).inc()
            OUTBOX_PROCESSING_EVENTS.labels(worker_id=self.worker_id).set(0)

        return processed

    async def _process_event(self, event: OutboxEvent) -> None:
        """
        Process a single event.

        Args:
            event: The event to process
        """
        start_time = time.time()
        event_type = event.event_type or "unknown"

        try:
            # Publish to broker
            await self.broker.publish_event(event)  # type: ignore[attr-defined]

            # Mark as sent
            await self.storage.update_status(
                event.event_id,
                OutboxStatus.SENT,
            )

            self._events_processed += 1

            # Record Prometheus metrics
            if PROMETHEUS_AVAILABLE:
                duration = time.time() - start_time
                OUTBOX_PUBLISHED_EVENTS.labels(
                    worker_id=self.worker_id, event_type=event_type
                ).inc()
                OUTBOX_PUBLISH_DURATION.labels(
                    worker_id=self.worker_id, event_type=event_type
                ).observe(duration)

            if self._on_event_published:
                await self._on_event_published(event)

            logger.debug(f"Event {event.event_id} published successfully")

        except BrokerError as e:  # pragma: no cover
            await self._handle_publish_failure(event, e)
        except Exception as e:  # pragma: no cover
            await self._handle_publish_failure(event, e)

    async def _handle_publish_failure(
        self,
        event: OutboxEvent,
        error: Exception,
    ) -> None:
        """
        Handle a publish failure.

        Args:
            event: The event that failed
            error: The exception that occurred
        """
        error_message = str(error)
        event_type = event.event_type or "unknown"

        logger.warning(
            f"Event {event.event_id} failed to publish: {error_message} "
            f"(attempt {event.retry_count + 1}/{self.config.max_retries})"
        )

        # Update to failed status
        event = await self.storage.update_status(
            event.event_id,
            OutboxStatus.FAILED,
            error_message=error_message,
        )

        self._events_failed += 1

        # Record Prometheus metrics
        if PROMETHEUS_AVAILABLE:
            OUTBOX_FAILED_EVENTS.labels(worker_id=self.worker_id, event_type=event_type).inc()
            OUTBOX_RETRY_ATTEMPTS.labels(worker_id=self.worker_id).inc()

        if self._on_event_failed:  # pragma: no cover
            await self._on_event_failed(event, error)

        # Check if should move to dead letter
        if event.retry_count >= self.config.max_retries:
            await self._move_to_dead_letter(event)
        else:
            # Reset to pending for retry
            await self.storage.update_status(
                event.event_id,
                OutboxStatus.PENDING,
            )

    async def _move_to_dead_letter(self, event: OutboxEvent) -> None:
        """
        Move an event to the dead letter queue.

        Args:
            event: The event to move
        """
        await self.storage.update_status(
            event.event_id,
            OutboxStatus.DEAD_LETTER,
        )

        self._events_dead_lettered += 1

        # Record Prometheus metrics
        if PROMETHEUS_AVAILABLE:
            event_type = event.event_type or "unknown"
            OUTBOX_DEAD_LETTER_EVENTS.labels(worker_id=self.worker_id, event_type=event_type).inc()

        logger.error(
            f"Event {event.event_id} moved to dead letter queue "
            f"after {event.retry_count} attempts. "
            f"Last error: {event.last_error}"
        )

    async def recover_stuck_events(self) -> int:
        """
        Recover events that appear stuck.

        This should be called periodically to handle events
        claimed by crashed workers.

        Returns:
            Number of events recovered
        """
        count = await self.storage.release_stuck_events(
            claimed_older_than_seconds=self.config.claim_timeout_seconds
        )

        if count > 0:
            logger.info(f"Recovered {count} stuck events")

        return count

    def get_stats(self) -> dict:
        """
        Get worker statistics.

        Returns:
            Dictionary of stats
        """
        return {
            "worker_id": self.worker_id,
            "running": self._running,
            "events_processed": self._events_processed,
            "events_failed": self._events_failed,
            "events_dead_lettered": self._events_dead_lettered,
        }


def get_storage():
    """Create storage backend from environment."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)

    from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage

    return PostgreSQLOutboxStorage(connection_string=database_url)


def _get_broker_url(broker_type: str) -> str:
    """Get broker URL from environment based on broker type."""
    if broker_type == "rabbitmq":
        return os.getenv("RABBITMQ_URL", "") or os.getenv("BROKER_URL", "")
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "") or os.getenv("BROKER_URL", "")


def _create_kafka_broker(broker_url: str):
    """Create Kafka broker instance."""
    from sagaz.outbox.brokers.kafka import KafkaBroker, KafkaBrokerConfig

    config = KafkaBrokerConfig(bootstrap_servers=broker_url)
    return KafkaBroker(config=config)


def _create_rabbitmq_broker(broker_url: str):
    """Create RabbitMQ broker instance."""
    from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker, RabbitMQBrokerConfig

    config = RabbitMQBrokerConfig(
        url=broker_url,
        exchange_name=os.getenv("RABBITMQ_EXCHANGE", "saga-events"),
    )
    return RabbitMQBroker(config=config)


_BROKER_FACTORIES = {
    "kafka": _create_kafka_broker,
    "rabbitmq": _create_rabbitmq_broker,
}


def get_broker():
    """Create broker from environment."""
    broker_type = os.getenv("BROKER_TYPE", "kafka").lower()
    broker_url = _get_broker_url(broker_type)

    if not broker_url:
        logger.error(f"No broker URL configured. Set BROKER_URL or {broker_type.upper()}_URL")
        sys.exit(1)

    factory = _BROKER_FACTORIES.get(broker_type)
    if not factory:
        logger.error(f"Unknown broker type: {broker_type}")
        sys.exit(1)

    return factory(broker_url)


async def main():
    """Main entry point."""
    logger.info("Startingsagaz Outbox Worker...")

    # Create storage and broker
    storage = get_storage()
    broker = get_broker()

    # Create worker config
    from sagaz.outbox.types import OutboxConfig

    config = OutboxConfig(
        batch_size=int(os.getenv("BATCH_SIZE", "100")),
        poll_interval_seconds=float(os.getenv("POLL_INTERVAL", "1.0")),
        max_retries=int(os.getenv("MAX_RETRIES", "5")),
    )

    # Create worker
    from sagaz.outbox.worker import OutboxWorker

    worker = OutboxWorker(
        storage=storage,
        broker=broker,
        config=config,
        worker_id=os.getenv("WORKER_ID"),
    )

    try:
        # Initialize connections
        logger.info("Initializing storage...")
        await storage.initialize()

        logger.info("Connecting to broker...")
        await broker.connect()

        logger.info(f"Worker {worker.worker_id} starting...")
        await worker.start()

    except KeyboardInterrupt:
        logger.info("Received shutdown signal...")
    finally:
        logger.info("Shutting down...")
        await worker.stop()
        await broker.close()
        await storage.close()
        logger.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
