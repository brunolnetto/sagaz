"""
Outbox storage interface.

Enhanced interface for outbox event persistence with transfer
and health check support.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from sagaz.core.storage.interfaces._outbox_defaults import _OutboxStorageDefaults

if TYPE_CHECKING:
    from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


class OutboxStorage(_OutboxStorageDefaults, ABC):
    """
    Abstract storage interface for outbox events.

    Implementations must ensure atomic operations for:
    - Inserting events with saga state (within transaction)
    - Claiming events with SKIP LOCKED for concurrency
    - Updating event status

    All implementations should support:
    - CRUD operations for outbox events
    - Batch claiming with worker assignment
    - Stuck event detection and recovery
    - Dead letter queue access

    Optional, with default implementations in ``_OutboxStorageDefaults``:
    - health_check() / get_statistics()
    - export_all() / import_record() / count() for transfer support
    - archive_events()
    - requeue_dead_letter_event() / purge_dead_letter_events() for the DLQ

    Usage:
        >>> storage = PostgreSQLOutboxStorage(pool)
        >>>
        >>> # Insert event atomically with saga state
        >>> async with transaction():
        ...     await saga_storage.save(saga)
        ...     await outbox_storage.insert(event, conn)
        >>>
        >>> # Claim events for processing
        >>> events = await outbox_storage.claim_batch(
        ...     worker_id="worker-1",
        ...     batch_size=100
        ... )
    """

    # ==========================================================================
    # Core Event Operations
    # ==========================================================================

    @abstractmethod
    async def insert(
        self,
        event: OutboxEvent,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """
        Insert a new outbox event.

        Args:
            event: The event to insert
            connection: Optional database connection (for transactions)

        Returns:
            The inserted event with any generated fields

        Raises:
            OutboxStorageError: If insert fails
        """
        ...

    @abstractmethod
    async def get_by_id(self, event_id: str) -> OutboxEvent | None:
        """
        Get an event by its ID.

        Args:
            event_id: The event ID

        Returns:
            The event if found, None otherwise
        """
        ...

    @abstractmethod
    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection: Any | None = None,
        event: OutboxEvent | None = None,
    ) -> OutboxEvent:
        """
        Update the status of an event.

        Args:
            event_id: ID of the event to update
            status: New status
            error_message: Optional error message (for FAILED status)
            connection: Optional database connection (for transactions)
            event: Optional full event carrying metadata to persist

        Returns:
            Updated event

        Raises:
            OutboxStorageError: If update fails
        """
        ...

    # ==========================================================================
    # Batch Operations
    # ==========================================================================

    @abstractmethod
    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """
        Claim a batch of pending events for processing.

        Uses FOR UPDATE SKIP LOCKED (or equivalent) to prevent
        concurrent claims.

        Args:
            worker_id: ID of the claiming worker
            batch_size: Maximum events to claim
            older_than_seconds: Only claim events older than this (for backoff)

        Returns:
            List of claimed events

        Raises:
            OutboxStorageError: If claim fails
        """
        ...

    @abstractmethod
    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """
        Get all events for a saga.

        Args:
            saga_id: The saga ID

        Returns:
            List of events for the saga
        """
        ...

    # ==========================================================================
    # Stuck Event Recovery
    # ==========================================================================

    @abstractmethod
    async def get_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> list[OutboxEvent]:
        """
        Get events that appear to be stuck (claimed but not processed).

        Args:
            claimed_older_than_seconds: Consider stuck if claimed longer ago

        Returns:
            List of stuck events
        """
        ...

    @abstractmethod
    async def release_stuck_events(
        self,
        claimed_older_than_seconds: float = 300.0,
    ) -> int:
        """
        Release stuck events back to PENDING status.

        Args:
            claimed_older_than_seconds: Release if claimed longer ago

        Returns:
            Number of events released
        """
        ...

    # ==========================================================================
    # Statistics and Queue Management
    # ==========================================================================

    @abstractmethod
    async def get_pending_count(self) -> int:
        """Get count of pending events."""
        ...

    @abstractmethod
    async def get_dead_letter_events(
        self,
        limit: int = 100,
    ) -> list[OutboxEvent]:
        """Get events in dead letter queue."""
        ...

    # ==========================================================================
    # Context Manager Support
    # ==========================================================================

    async def __aenter__(self) -> OutboxStorage:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""

    async def close(self) -> None:
        """
        Close the storage and release resources.

        Override if your backend needs cleanup.
        """


# ==========================================================================
# Errors
# ==========================================================================


class OutboxStorageError(Exception):
    """Base exception for outbox storage errors."""
