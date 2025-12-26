"""
Outbox Storage - Base classes and interface.

Provides an abstract interface for storing outbox events.
"""

from abc import ABC, abstractmethod
from typing import Any

from sagaz.outbox.types import OutboxEvent, OutboxStatus


class OutboxStorageError(Exception):
    """Base exception for outbox storage errors."""


class OutboxStorage(ABC):
    """
    Abstract storage interface for outbox events.
    
    Implementations must ensure atomic operations for:
    - Inserting events with saga state (within transaction)
    - Claiming events with SKIP LOCKED for concurrency
    - Updating event status
    
    Usage:
        >>> storage = PostgresOutboxStorage(pool)
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
    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int = 100,
        older_than_seconds: float = 0.0,
    ) -> list[OutboxEvent]:
        """
        Claim a batch of pending events for processing.
        
        Uses FOR UPDATE SKIP LOCKED to prevent concurrent claims.
        
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
    async def update_status(
        self,
        event_id: str,
        status: OutboxStatus,
        error_message: str | None = None,
        connection: Any | None = None,
    ) -> OutboxEvent:
        """
        Update the status of an event.
        
        Args:
            event_id: ID of the event to update
            status: New status
            error_message: Optional error message (for FAILED status)
            connection: Optional database connection (for transactions)
        
        Returns:
            Updated event
        
        Raises:
            OutboxStorageError: If update fails
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
    async def get_events_by_saga(self, saga_id: str) -> list[OutboxEvent]:
        """
        Get all events for a saga.
        
        Args:
            saga_id: The saga ID
        
        Returns:
            List of events for the saga
        """
        ...

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
