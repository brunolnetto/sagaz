"""
In-Memory Outbox Storage - For testing and development.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sagaz.outbox.storage.base import OutboxStorage, OutboxStorageError
from sagaz.outbox.types import OutboxEvent, OutboxStatus


class InMemoryOutboxStorage(OutboxStorage):
    """
    In-memory implementation of outbox storage for testing.

    Thread-safe for async operations but not for multi-process.

    Usage:
        >>> storage = InMemoryOutboxStorage()
        >>> event = OutboxEvent(saga_id="123", event_type="Test", payload={})
        >>> await storage.insert(event)
        >>>
        >>> claimed = await storage.claim_batch("worker-1", batch_size=10)
    """

    def __init__(self):
        self._events: dict[str, OutboxEvent] = {}

    async def insert(
        self,
        event: OutboxEvent,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Insert event into in-memory storage."""
        self._events[event.event_id] = event
        return event

    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """Claim batch of pending events."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=older_than_seconds)

        claimed: list[OutboxEvent] = []
        for event in list(self._events.values()):
            if len(claimed) >= batch_size:
                break

            if event.status == OutboxStatus.PENDING and event.created_at <= cutoff:
                event.status = OutboxStatus.CLAIMED
                event.worker_id = worker_id
                event.claimed_at = now
                claimed.append(event)

        return claimed

    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """Update event status."""
        event = self._events.get(event_id)
        if not event:
            msg = f"Event {event_id} not found"
            raise OutboxStorageError(msg)

        event.status = status

        if status == OutboxStatus.SENT:
            event.sent_at = datetime.now(UTC)
        elif status == OutboxStatus.FAILED:
            event.retry_count += 1
            event.last_error = error_message
        elif status == OutboxStatus.PENDING:
            event.worker_id = None
            event.claimed_at = None

        return event

    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """Get event by ID."""
        return self._events.get(event_id)

    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """Get all events for a saga."""
        return [e for e in self._events.values() if e.saga_id == saga_id]

    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """Get stuck events."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=claimed_older_than_seconds)

        return [
            e
            for e in self._events.values()
            if e.status == OutboxStatus.CLAIMED and e.claimed_at and e.claimed_at < cutoff
        ]

    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:
        """Release stuck events."""
        stuck = await self.get_stuck_events(claimed_older_than_seconds)

        for event in stuck:
            event.status = OutboxStatus.PENDING
            event.worker_id = None
            event.claimed_at = None

        return len(stuck)

    async def get_pending_count(self) -> int:
        """Get count of pending events."""
        return sum(1 for e in self._events.values() if e.status == OutboxStatus.PENDING)

    async def get_dead_letter_events(
        self,
        limit: int = 100,
    ) -> list[OutboxEvent]:
        """Get dead letter events."""
        return [
            e for e in list(self._events.values())[:limit] if e.status == OutboxStatus.DEAD_LETTER
        ]

    def clear(self) -> None:
        """Clear all events (for testing)."""
        self._events.clear()
