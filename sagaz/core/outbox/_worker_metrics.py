"""
Prometheus metrics for the outbox worker.

Declares the worker's metrics (gracefully degrading to ``None`` when
``prometheus-client`` is not installed) and a mixin that records them.
All names are re-exported from :mod:`sagaz.core.outbox.worker`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sagaz.core.outbox._worker_logging import logger

if TYPE_CHECKING:
    import prometheus_client

    from sagaz.core.outbox.types import OutboxEvent
    from sagaz.core.storage.interfaces.outbox import OutboxStorage


OUTBOX_BATCH_PROCESSED: prometheus_client.Counter | None
OUTBOX_PUBLISHED_EVENTS: prometheus_client.Counter | None
OUTBOX_FAILED_EVENTS: prometheus_client.Counter | None
OUTBOX_DEAD_LETTER_EVENTS: prometheus_client.Counter | None
OUTBOX_REPLAY_LOOP_DETECTED: prometheus_client.Counter | None
OUTBOX_RETRY_ATTEMPTS: prometheus_client.Counter | None
OUTBOX_PENDING_EVENTS: prometheus_client.Gauge | None
OUTBOX_PROCESSING_EVENTS: prometheus_client.Gauge | None
OUTBOX_BATCH_SIZE: prometheus_client.Gauge | None
OUTBOX_EVENTS_BY_STATE: prometheus_client.Gauge | None
OUTBOX_DLQ_DEPTH: prometheus_client.Gauge | None
OUTBOX_PUBLISH_DURATION: prometheus_client.Histogram | None

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
        ["worker_id", "event_type", "error_type"],
    )

    OUTBOX_REPLAY_LOOP_DETECTED = Counter(
        "outbox_replay_loop_detected_total",
        "Total replay loop guard activations (event blocked from further replay)",
        ["worker_id"],
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

    OUTBOX_DLQ_DEPTH = Gauge(
        "sagaz_dlq_depth",
        "Current number of events in the dead letter queue",
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
    OUTBOX_BATCH_PROCESSED = None
    OUTBOX_PUBLISHED_EVENTS = None
    OUTBOX_FAILED_EVENTS = None
    OUTBOX_DEAD_LETTER_EVENTS = None
    OUTBOX_RETRY_ATTEMPTS = None
    OUTBOX_REPLAY_LOOP_DETECTED = None
    OUTBOX_PENDING_EVENTS = None
    OUTBOX_PROCESSING_EVENTS = None
    OUTBOX_BATCH_SIZE = None
    OUTBOX_EVENTS_BY_STATE = None
    OUTBOX_DLQ_DEPTH = None
    OUTBOX_PUBLISH_DURATION = None
    logger.debug("prometheus-client not installed, metrics disabled")


class OutboxWorkerMetricsMixin:
    """Record the outbox worker's Prometheus metrics (no-ops when unavailable)."""

    worker_id: str
    storage: OutboxStorage

    async def _update_pending_gauge(self) -> None:
        """Refresh the pending-events gauge from storage."""
        if PROMETHEUS_AVAILABLE and OUTBOX_PENDING_EVENTS is not None:
            try:
                pending_count = await self.storage.get_pending_count()
                OUTBOX_PENDING_EVENTS.set(pending_count)
            except Exception:
                pass  # Ignore errors when getting pending count

    def _record_batch_started(self, batch_size: int) -> None:
        """Record metrics for a newly claimed batch."""
        if (
            PROMETHEUS_AVAILABLE
            and OUTBOX_BATCH_SIZE is not None
            and OUTBOX_PROCESSING_EVENTS is not None
        ):
            OUTBOX_BATCH_SIZE.labels(worker_id=self.worker_id).set(batch_size)
            OUTBOX_PROCESSING_EVENTS.labels(worker_id=self.worker_id).set(batch_size)

    def _record_batch_completed(self) -> None:
        """Record completion metrics and clear the in-flight gauge."""
        if (
            PROMETHEUS_AVAILABLE
            and OUTBOX_BATCH_PROCESSED is not None
            and OUTBOX_PROCESSING_EVENTS is not None
        ):
            OUTBOX_BATCH_PROCESSED.labels(worker_id=self.worker_id).inc()
            OUTBOX_PROCESSING_EVENTS.labels(worker_id=self.worker_id).set(0)

    def _record_published(self, event_type: str, start_time: float) -> None:
        """Record a successful publish and its duration."""
        if (
            PROMETHEUS_AVAILABLE
            and OUTBOX_PUBLISHED_EVENTS is not None
            and OUTBOX_PUBLISH_DURATION is not None
        ):
            duration = time.time() - start_time
            OUTBOX_PUBLISHED_EVENTS.labels(worker_id=self.worker_id, event_type=event_type).inc()
            OUTBOX_PUBLISH_DURATION.labels(worker_id=self.worker_id, event_type=event_type).observe(
                duration
            )

    def _record_failed(self, event_type: str) -> None:
        """Record a failed publish attempt."""
        if (
            PROMETHEUS_AVAILABLE
            and OUTBOX_FAILED_EVENTS is not None
            and OUTBOX_RETRY_ATTEMPTS is not None
        ):
            OUTBOX_FAILED_EVENTS.labels(worker_id=self.worker_id, event_type=event_type).inc()
            OUTBOX_RETRY_ATTEMPTS.labels(worker_id=self.worker_id).inc()

    def _record_dead_lettered(self, event: OutboxEvent) -> None:
        """Record an event moved to the dead letter queue."""
        if (
            PROMETHEUS_AVAILABLE
            and OUTBOX_DEAD_LETTER_EVENTS is not None
            and OUTBOX_DLQ_DEPTH is not None
        ):
            event_type = event.event_type or "unknown"
            error_type_label = event.error_type or "unknown"
            OUTBOX_DEAD_LETTER_EVENTS.labels(
                worker_id=self.worker_id,
                event_type=event_type,
                error_type=error_type_label,
            ).inc()
            OUTBOX_DLQ_DEPTH.inc()
