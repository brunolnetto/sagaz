"""
Outbox Worker - Background processor for outbox events.

Polls the outbox for pending events and publishes them to the message broker.
Handles retries, dead-letter queue, and graceful shutdown.

Usage:
    >>> from sagaz.core.outbox import OutboxWorker, InMemoryOutboxStorage, InMemoryBroker
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

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from collections.abc import Awaitable, Callable

from sagaz.core.outbox._worker_bootstrap import get_broker as get_broker
from sagaz.core.outbox._worker_bootstrap import get_storage as get_storage
from sagaz.core.outbox._worker_failures import OutboxWorkerFailureMixin
from sagaz.core.outbox._worker_logging import log_level as log_level
from sagaz.core.outbox._worker_logging import logger

# Metrics live in _worker_metrics; re-exported here for backward compatibility.
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_BATCH_PROCESSED as OUTBOX_BATCH_PROCESSED,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_BATCH_SIZE as OUTBOX_BATCH_SIZE,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_DEAD_LETTER_EVENTS as OUTBOX_DEAD_LETTER_EVENTS,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_DLQ_DEPTH as OUTBOX_DLQ_DEPTH,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_EVENTS_BY_STATE as OUTBOX_EVENTS_BY_STATE,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_FAILED_EVENTS as OUTBOX_FAILED_EVENTS,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_PENDING_EVENTS as OUTBOX_PENDING_EVENTS,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_PROCESSING_EVENTS as OUTBOX_PROCESSING_EVENTS,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_PUBLISH_DURATION as OUTBOX_PUBLISH_DURATION,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_PUBLISHED_EVENTS as OUTBOX_PUBLISHED_EVENTS,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_REPLAY_LOOP_DETECTED as OUTBOX_REPLAY_LOOP_DETECTED,
)
from sagaz.core.outbox._worker_metrics import (
    OUTBOX_RETRY_ATTEMPTS as OUTBOX_RETRY_ATTEMPTS,
)
from sagaz.core.outbox._worker_metrics import (
    PROMETHEUS_AVAILABLE as PROMETHEUS_AVAILABLE,
)
from sagaz.core.outbox.brokers.base import BrokerError, MessageBroker
from sagaz.core.outbox.state_machine import OutboxStateMachine
from sagaz.core.outbox.types import OutboxConfig, OutboxEvent, OutboxStatus
from sagaz.core.storage.interfaces.outbox import OutboxStorage
from sagaz.core.tenant import system_scope, tenant_scope


class OutboxWorker(OutboxWorkerFailureMixin):
    """
    Background worker that processes outbox events.

    Features:
        - Batch processing for efficiency
        - Parallel publish within batches
        - Exponential backoff on failures
        - Graceful shutdown on SIGTERM/SIGINT
        - Stuck event recovery
        - Dead letter queue handling
        - Multi-tenant (ADR-020): claims run in the system scope, so the worker
          publishes every tenant's events; each event is then published and
          updated inside its own tenant's scope, and the broker message carries
          its ``tenant_id``

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
        self._shutdown_task: asyncio.Task | None = None

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
            with system_scope():
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
            except NotImplementedError:
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
            await self._update_pending_gauge()

            processed = await self.process_batch()
            if processed == 0:
                await self._wait_for_next_poll()
            return False
        except TimeoutError:
            return False  # Normal timeout, continue loop
        except asyncio.CancelledError:
            logger.info(f"Worker {self.worker_id} cancelled")
            return True
        except Exception as e:
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

    def _count_batch_results(
        self,
        events: list[OutboxEvent],
        results: list[None | BaseException],
    ) -> int:
        """Log failed events and return the number of successful events."""
        processed = 0
        for event, result in zip(events, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"Failed to process event {event.event_id}: {result}")
            else:
                processed += 1
        return processed

    async def process_batch(self) -> int:
        """
        Process a single batch of events.

        Returns:
            Number of events processed
        """
        with system_scope():
            events = await self.storage.claim_batch(
                worker_id=self.worker_id,
                batch_size=self.config.batch_size,
            )
        if not events:
            return 0

        batch_size = len(events)
        logger.debug(f"Worker {self.worker_id} claimed {batch_size} events")
        self._record_batch_started(batch_size)

        tasks = [self._process_event(event) for event in events]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = self._count_batch_results(events, results)
        self._record_batch_completed()
        return processed

    async def _process_event(self, event: OutboxEvent) -> None:
        """
        Process a single event inside the scope of the tenant that owns it.

        Args:
            event: The event to process
        """
        with tenant_scope(event.tenant_id):
            await self._publish_and_record(event)

    async def _publish_and_record(self, event: OutboxEvent) -> None:
        """Publish ``event`` and record the outcome in storage."""
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
            self._record_published(event_type, start_time)
            if self._on_event_published:
                await self._on_event_published(event)

            logger.debug(f"Event {event.event_id} published successfully")

        except BrokerError as e:
            await self._handle_publish_failure(event, e)
        except Exception as e:
            await self._handle_publish_failure(event, e)

    async def recover_stuck_events(self) -> int:
        """
        Recover events that appear stuck.

        This should be called periodically to handle events
        claimed by crashed workers.

        Returns:
            Number of events recovered
        """
        with system_scope():
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


async def main():
    """Main entry point."""
    logger.info("Startingsagaz Outbox Worker...")

    # Create storage and broker
    storage = get_storage()
    broker = get_broker()

    config = OutboxConfig(
        batch_size=int(os.getenv("BATCH_SIZE", "100")),
        poll_interval_seconds=float(os.getenv("POLL_INTERVAL", "1.0")),
        max_retries=int(os.getenv("MAX_RETRIES", "5")),
    )

    # Create worker

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
