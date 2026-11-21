"""
Optimistic event publishing - attempts immediate broker publish after commit.

Reduces latency from ~100ms (polling) to <10ms (immediate) in happy path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sagaz.core.outbox._metrics import PROMETHEUS_AVAILABLE, Counter, Histogram

from .types import OutboxEvent, OutboxStatus

if TYPE_CHECKING:
    from sagaz.core.outbox.brokers.base import BaseBroker
    from sagaz.core.storage.interfaces import OutboxStorage

logger = logging.getLogger(__name__)


# Metrics (no-op if prometheus not installed)
OPTIMISTIC_SEND_ATTEMPTS = Counter(
    "outbox_optimistic_send_attempts_total", "Total optimistic send attempts"
)
OPTIMISTIC_SEND_SUCCESS = Counter(
    "outbox_optimistic_send_success_total", "Successful optimistic sends"
)
OPTIMISTIC_SEND_FAILURES = Counter(
    "outbox_optimistic_send_failures_total",
    "Failed optimistic sends (will fallback to polling)",
    ["reason"],
)
OPTIMISTIC_SEND_LATENCY = Histogram(
    "outbox_optimistic_send_latency_seconds",
    "Latency of optimistic send operation",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


class OptimisticPublisher:
    """
    Publishes events immediately after transaction commit.

    Benefits:
    - 10x faster than polling (< 10ms vs ~100ms)
    - Still maintains exactly-once semantics
    - Failures fallback to polling worker (safety net)
    """

    def __init__(
        self,
        storage: OutboxStorage,
        broker: BaseBroker,
        enabled: bool = True,
        timeout_seconds: float = 0.5,
    ) -> None:
        self.storage = storage
        self.broker = broker
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds

    async def publish_after_commit(self, event: OutboxEvent) -> bool:
        """
        Attempt immediate publish after transaction commits.

        CRITICAL: Call AFTER transaction commit, not before!

        Returns:
            True if published successfully, False if failed (will fallback)
        """
        if not self.enabled:
            return False

        OPTIMISTIC_SEND_ATTEMPTS.inc()

        try:
            with OPTIMISTIC_SEND_LATENCY.time():
                # The outbox worker publishes the same way: an event reaches the same
                # topic, in the same format, whichever path delivers it.
                await asyncio.wait_for(
                    self.broker.publish_event(event),
                    timeout=self.timeout_seconds,
                )

            # Success!
            await self.storage.update_status(event.event_id, OutboxStatus.SENT)
            OPTIMISTIC_SEND_SUCCESS.inc()

            logger.info(f"Optimistic send succeeded: {event.event_id}")
            return True

        except TimeoutError:
            OPTIMISTIC_SEND_FAILURES.labels(reason="timeout").inc()
            logger.warning(f"Optimistic timeout: {event.event_id}, will fallback")
            return False

        except Exception as exc:
            OPTIMISTIC_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
            logger.warning(f"Optimistic failed: {event.event_id}, will fallback: {exc}")
            return False
