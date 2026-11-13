"""
Publish-failure handling for the outbox worker: error classification, retry
bookkeeping and moving exhausted events to the dead letter queue.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sagaz.core.outbox._worker_logging import logger
from sagaz.core.outbox._worker_metrics import OutboxWorkerMetricsMixin
from sagaz.core.outbox.error_classifier import classify_error, create_error_fingerprint
from sagaz.core.outbox.types import OutboxEvent, OutboxStatus

if TYPE_CHECKING:
    from sagaz.core.outbox.types import OutboxConfig


class OutboxWorkerFailureMixin(OutboxWorkerMetricsMixin):
    """Handle failed publishes: mark FAILED, then retry or dead-letter."""

    config: OutboxConfig
    _on_event_failed: Callable[[OutboxEvent, Exception], Awaitable[None]] | None
    _events_failed: int
    _events_dead_lettered: int

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

        # Phase 1: classify and fingerprint the error before any storage update
        event.error_type = type(error).__name__
        event.error_classification = classify_error(error)
        event.error_fingerprint = create_error_fingerprint(error_message)

        logger.warning(
            f"Event {event.event_id} failed to publish: {error_message} "
            f"(attempt {event.retry_count + 1}/{self.config.max_retries})"
        )

        # Update to failed status
        event = await self.storage.update_status(
            event.event_id,
            OutboxStatus.FAILED,
            error_message=error_message,
            event=event,
        )

        self._events_failed += 1

        # Record Prometheus metrics
        self._record_failed(event_type)

        if self._on_event_failed:
            await self._on_event_failed(event, error)

        # Check if should move to dead letter
        if event.retry_count >= self.config.max_retries:
            await self._move_to_dead_letter(event)
        else:
            # Reset to pending for retry
            await self.storage.update_status(
                event.event_id,
                OutboxStatus.PENDING,
                event=event,
            )

    async def _move_to_dead_letter(self, event: OutboxEvent) -> None:
        """
        Move an event to the dead letter queue.

        Args:
            event: The event to move
        """
        event.dead_letter_at = datetime.now(UTC)
        event.dead_letter_reason = event.last_error or "max_retries_exceeded"

        await self.storage.update_status(
            event.event_id,
            OutboxStatus.DEAD_LETTER,
            error_message=event.dead_letter_reason,
            event=event,
        )

        self._events_dead_lettered += 1

        # Record Prometheus metrics
        self._record_dead_lettered(event)

        logger.error(
            f"Event {event.event_id} moved to dead letter queue "
            f"after {event.retry_count} attempts. "
            f"Last error: {event.last_error}"
        )
