# ============================================
# FILE: sagaz/storage/interfaces/snapshot.py
# ============================================

"""
Snapshot Storage Interface

Defines the contract for storing and retrieving saga snapshots
for replay and time-travel features.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

from sagaz.core.replay import ReplayResult, SagaSnapshot


class SnapshotStorage(ABC):
    """Abstract interface for snapshot storage"""

    @abstractmethod
    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """
        Save a saga snapshot.

        Args:
            snapshot: The snapshot to save

        Raises:
            SnapshotCaptureError: If snapshot cannot be saved
        """

    @abstractmethod
    async def get_snapshot(self, snapshot_id: UUID) -> SagaSnapshot | None:
        """
        Retrieve a specific snapshot by ID.

        Args:
            snapshot_id: UUID of the snapshot

        Returns:
            SagaSnapshot if found, None otherwise
        """

    @abstractmethod
    async def get_latest_snapshot(
        self, saga_id: UUID, before_step: str | None = None
    ) -> SagaSnapshot | None:
        """
        Get the most recent snapshot for a saga.

        Args:
            saga_id: UUID of the saga
            before_step: Optional step name to get snapshot before this step

        Returns:
            Latest SagaSnapshot if found, None otherwise
        """

    @abstractmethod
    async def get_snapshot_at_time(
        self, saga_id: UUID, timestamp: datetime
    ) -> SagaSnapshot | None:
        """
        Get the snapshot closest to (but not after) given timestamp.

        Args:
            saga_id: UUID of the saga
            timestamp: Target timestamp

        Returns:
            SagaSnapshot at or before timestamp, None if not found
        """

    @abstractmethod
    async def list_snapshots(
        self, saga_id: UUID, limit: int = 100
    ) -> list[SagaSnapshot]:
        """
        List all snapshots for a saga.

        Args:
            saga_id: UUID of the saga
            limit: Maximum number of snapshots to return

        Returns:
            List of snapshots ordered by created_at DESC
        """

    @abstractmethod
    async def delete_snapshot(self, snapshot_id: UUID) -> bool:
        """
        Delete a specific snapshot.

        Args:
            snapshot_id: UUID of the snapshot

        Returns:
            True if deleted, False if not found
        """

    @abstractmethod
    async def delete_expired_snapshots(self) -> int:
        """
        Delete snapshots past their retention period.

        Returns:
            Number of snapshots deleted
        """

    @abstractmethod
    async def save_replay_log(self, replay_result: ReplayResult) -> None:
        """
        Save replay operation result for audit trail.

        Args:
            replay_result: The replay result to log
        """

    @abstractmethod
    async def get_replay_log(self, replay_id: UUID) -> dict[str, Any] | None:
        """
        Retrieve replay log entry.

        Args:
            replay_id: UUID of the replay operation

        Returns:
            Replay log data if found, None otherwise
        """

    @abstractmethod
    async def list_replays(
        self, original_saga_id: UUID, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        List all replay operations for a saga.

        Args:
            original_saga_id: UUID of the original saga
            limit: Maximum number of replays to return

        Returns:
            List of replay log entries
        """
