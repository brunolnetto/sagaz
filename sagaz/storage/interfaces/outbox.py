"""
Outbox storage interface.

Enhanced interface for outbox event persistence with transfer
and health check support.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from sagaz.storage.core import HealthCheckResult, StorageStatistics

if TYPE_CHECKING:
    from sagaz.outbox.types import OutboxEvent, OutboxStatus


class OutboxStorage(ABC):
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

    Optional (for transfer support):
    - export_all() for exporting records
    - import_record() for importing records
    - count() for getting total count

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
    # Health Check (Optional but Recommended)
    # ==========================================================================

    async def health_check(self) -> HealthCheckResult:
        """
        Check storage health.

        Override to provide backend-specific health checks.

        Returns:
            HealthCheckResult with status and details
        """
        from sagaz.storage.core import HealthStatus

        try:
            count = await self.get_pending_count()
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                latency_ms=0,
                message="OK",
                details={"pending_count": count},
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=0,
                message=str(e),
            )

    async def get_statistics(self) -> StorageStatistics:
        """
        Get storage statistics.

        Override for backend-specific statistics.

        Returns:
            StorageStatistics with usage information
        """
        pending = await self.get_pending_count()
        return StorageStatistics(
            pending_records=pending,
        )

    # ==========================================================================
    # Transfer Support (Optional - Not Required)
    # ==========================================================================

    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        """
        Export all outbox events as dictionaries.

        Override to enable data transfer from this backend.

        Yields:
            Dict representation of each outbox event
        """
        msg = (
            f"{self.__class__.__name__} does not support export. "
            "Implement export_all() to enable data transfer."
        )
        raise NotImplementedError(
            msg
        )
        # Make it a generator
        if False:
            yield {}

    async def import_record(self, record: dict[str, Any]) -> None:
        """
        Import a single outbox event record.

        Override to enable data transfer to this backend.

        Args:
            record: Dict representation of outbox event
        """
        msg = (
            f"{self.__class__.__name__} does not support import. "
            "Implement import_record() to enable data transfer."
        )
        raise NotImplementedError(
            msg
        )

    async def count(self) -> int:
        """
        Get total event count.

        Override for efficient counting (used for transfer progress).

        Returns:
            Number of events in storage
        """
        return await self.get_pending_count()

    # ==========================================================================
    # Archival (Optional)
    # ==========================================================================

    async def archive_events(
        self,
        older_than_days: int = 30,
        statuses: list[OutboxStatus] | None = None,
    ) -> int:
        """
        Archive old events (move to archive table or delete).

        Override if your backend supports archival.

        Args:
            older_than_days: Archive events older than this
            statuses: Only archive events with these statuses
                      (default: PUBLISHED)

        Returns:
            Number of events archived
        """
        msg = f"{self.__class__.__name__} does not support archival."
        raise NotImplementedError(
            msg
        )

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
