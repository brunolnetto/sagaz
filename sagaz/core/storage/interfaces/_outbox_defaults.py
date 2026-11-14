"""Default implementations of the optional OutboxStorage capabilities.

Health check, statistics, transfer (export/import/count), archival and the
dead-letter queue operations. Backends override what they support; the
defaults either derive from ``get_pending_count()`` or raise
``NotImplementedError`` with a message naming the backend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sagaz.core.storage.core import HealthCheckResult, StorageStatistics

if TYPE_CHECKING:
    from sagaz.core.outbox.types import OutboxEvent, OutboxStatus


class _OutboxStorageDefaults:
    """Optional OutboxStorage operations with overridable defaults."""

    if TYPE_CHECKING:

        async def get_pending_count(self) -> int: ...

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
        from sagaz.core.storage.core import HealthStatus

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
        raise NotImplementedError(msg)
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
        raise NotImplementedError(msg)

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
        raise NotImplementedError(msg)

    async def requeue_dead_letter_event(self, event_id: str, force: bool = False) -> OutboxEvent:
        """
        Move a DLQ event back to PENDING for reprocessing.

        Resets retry_count to 0 and clears dead_letter_at / dead_letter_reason.
        Increments replay_count and raises ReplayLoopError when the count
        reaches the configured maximum (unless *force* is True).

        Args:
            event_id: The ID of the DLQ event to requeue.
            force: Bypass the replay-loop guard when True.

        Returns:
            The updated event with PENDING status.

        Raises:
            KeyError: If the event is not found.
            ReplayLoopError: If replay_count >= max_replays and force is False.
        """
        msg = f"{self.__class__.__name__} does not implement requeue_dead_letter_event."
        raise NotImplementedError(msg)

    async def purge_dead_letter_events(
        self,
        older_than: timedelta | None = None,
    ) -> int:
        """
        Permanently remove DLQ events.

        Args:
            older_than: If provided, only remove events whose dead_letter_at
                        is older than this duration.  All DLQ events are
                        removed when None.

        Returns:
            Number of events purged.
        """
        msg = f"{self.__class__.__name__} does not implement purge_dead_letter_events."
        raise NotImplementedError(msg)
