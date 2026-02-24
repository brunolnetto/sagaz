"""
In-Memory Outbox Storage - For testing and development.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Any

from sagaz.storage.interfaces.outbox import OutboxStorage, OutboxStorageError

if TYPE_CHECKING:
    from sagaz.outbox.types import OutboxEvent, OutboxStatus


def _get_outbox_status():
    """Lazy import of OutboxStatus to avoid circular imports."""
    from sagaz.outbox.types import OutboxStatus

    return OutboxStatus


def _get_outbox_event():
    """Lazy import of OutboxEvent to avoid circular imports."""
    from sagaz.outbox.types import OutboxEvent

    return OutboxEvent


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
        outbox_status_cls = _get_outbox_status()
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=older_than_seconds)

        claimed: list[OutboxEvent] = []
        for event in list(self._events.values()):
            if len(claimed) >= batch_size:
                break

            if event.status == outbox_status_cls.PENDING and event.created_at <= cutoff:
                event.status = outbox_status_cls.CLAIMED
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
        outbox_status_cls = _get_outbox_status()
        event = self._events.get(event_id)
        if not event:
            msg = f"Event {event_id} not found"
            raise OutboxStorageError(msg)

        event.status = status

        if status == outbox_status_cls.SENT:
            event.sent_at = datetime.now(UTC)
        elif status == outbox_status_cls.FAILED:
            event.retry_count += 1
            event.last_error = error_message
        elif status == outbox_status_cls.PENDING:
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
        outbox_status_cls = _get_outbox_status()
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=claimed_older_than_seconds)

        return [
            e
            for e in self._events.values()
            if e.status == outbox_status_cls.CLAIMED and e.claimed_at and e.claimed_at < cutoff
        ]

    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:
        """Release stuck events."""
        outbox_status_cls = _get_outbox_status()
        stuck = await self.get_stuck_events(claimed_older_than_seconds)

        for event in stuck:
            event.status = outbox_status_cls.PENDING
            event.worker_id = None
            event.claimed_at = None

        return len(stuck)

    async def get_pending_count(self) -> int:
        """Get count of pending events."""
        outbox_status_cls = _get_outbox_status()
        return sum(1 for e in self._events.values() if e.status == outbox_status_cls.PENDING)

    async def get_dead_letter_events(
        self,
        limit: int = 100,
    ) -> list[OutboxEvent]:
        """Get dead letter events."""
        outbox_status_cls = _get_outbox_status()
        return [
            e
            for e in list(self._events.values())[:limit]
            if e.status == outbox_status_cls.DEAD_LETTER
        ]

    def clear(self) -> None:
        """Clear all events (for testing)."""
        self._events.clear()

    async def count(self) -> int:
        """Count total events."""
        return len(self._events)

    async def export_all(self):
        """Export all records for transfer."""
        # Sort by ID
        sorted_events = sorted(self._events.values(), key=lambda x: x.event_id)
        for event in sorted_events:
            yield {
                "event_id": event.event_id,
                "saga_id": event.saga_id,
                "event_type": event.event_type,
                "payload": event.payload,
                "status": event.status.value,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record from transfer."""
        outbox_event_cls = _get_outbox_event()
        outbox_status_cls = _get_outbox_status()
        event = outbox_event_cls(
            event_id=record.get("event_id"),
            saga_id=record["saga_id"],
            event_type=record["event_type"],
            payload=record.get("payload", {}),
            status=outbox_status_cls(record.get("status", "pending")),
        )
        await self.insert(event)
