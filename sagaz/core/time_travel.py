# ============================================
# FILE: sagaz/core/time_travel.py
# ============================================

"""
Saga Time-Travel - Query Historical State

Allows querying saga state at any point in time by reconstructing from snapshots.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Any
from uuid import UUID

from sagaz.core.replay import SagaSnapshot
from sagaz.storage.interfaces.snapshot import SnapshotStorage

logger = logging.getLogger(__name__)


@dataclass
class HistoricalState:
    """Represents saga state at a specific point in time"""

    saga_id: UUID
    saga_name: str
    timestamp: datetime
    status: str
    context: dict[str, Any]
    completed_steps: list[str]
    current_step: str | None
    step_index: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "saga_id": str(self.saga_id),
            "saga_name": self.saga_name,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "context": self.context,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "step_index": self.step_index,
        }


class SagaTimeTravel:
    """
    Query historical saga state using snapshots.

    Example:
        time_travel = SagaTimeTravel(
            saga_id=UUID("abc-123"),
            snapshot_storage=storage
        )

        # Get state at specific time
        state = await time_travel.get_state_at(
            timestamp=datetime(2024, 12, 15, 10, 30, 0, tzinfo=timezone.utc)
        )

        # List state changes
        changes = await time_travel.list_state_changes()
    """

    def __init__(
        self,
        saga_id: UUID,
        snapshot_storage: SnapshotStorage,
    ):
        self.saga_id = saga_id
        self.snapshot_storage = snapshot_storage

    async def get_state_at(
        self,
        timestamp: datetime,
    ) -> HistoricalState | None:
        """
        Get saga state at a specific point in time.

        Args:
            timestamp: The point in time to query

        Returns:
            HistoricalState or None if no state exists at that time
        """
        logger.info(f"Time-travel query: saga_id={self.saga_id}, timestamp={timestamp}")

        # Ensure timestamp is timezone-aware
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        # Find the latest snapshot before or at the target timestamp
        snapshot = await self._find_snapshot_before(timestamp)

        if not snapshot:
            logger.warning(f"No snapshot found before {timestamp} for saga {self.saga_id}")
            return None

        # Reconstruct state from snapshot
        state = self._reconstruct_state(snapshot, timestamp)

        logger.info(
            f"Time-travel successful: found state at step '{state.current_step}' "
            f"(snapshot from {snapshot.created_at})"
        )

        return state

    async def list_state_changes(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
        limit: int = 100,
    ) -> list[HistoricalState]:
        """
        List all state changes (snapshots) within a time range.

        Args:
            after: Only return states after this time
            before: Only return states before this time
            limit: Maximum number of states to return

        Returns:
            List of HistoricalState objects in chronological order
        """
        logger.info(
            f"Listing state changes: saga_id={self.saga_id}, "
            f"after={after}, before={before}, limit={limit}"
        )

        # Get all snapshots for this saga
        snapshots = await self.snapshot_storage.list_snapshots(self.saga_id)

        # Filter by time range
        filtered = []
        for snapshot in snapshots:
            if after and snapshot.created_at < after:
                continue
            if before and snapshot.created_at > before:
                continue
            filtered.append(snapshot)

        # Sort by timestamp (oldest first)
        filtered.sort(key=lambda s: s.created_at)

        # Apply limit
        filtered = filtered[:limit]

        # Convert to HistoricalState
        states = [self._reconstruct_state(snapshot, snapshot.created_at) for snapshot in filtered]

        logger.info(f"Found {len(states)} state changes")
        return states

    async def get_context_at(
        self,
        timestamp: datetime,
        key: str | None = None,
    ) -> Any:
        """
        Get context value(s) at a specific point in time.

        Args:
            timestamp: The point in time to query
            key: Specific context key (returns all if None)

        Returns:
            Context value or dict of all context
        """
        state = await self.get_state_at(timestamp)
        if not state:
            return None

        if key:
            return state.context.get(key)
        return state.context

    async def _find_snapshot_before(
        self,
        timestamp: datetime,
    ) -> SagaSnapshot | None:
        """Find the latest snapshot before or at the given timestamp"""
        # Get all snapshots
        snapshots = await self.snapshot_storage.list_snapshots(self.saga_id)

        # Filter snapshots before or at timestamp
        candidates = [s for s in snapshots if s.created_at <= timestamp]

        if not candidates:
            return None

        # Return the latest one
        return max(candidates, key=lambda s: s.created_at)

    def _reconstruct_state(
        self,
        snapshot: SagaSnapshot,
        timestamp: datetime,
    ) -> HistoricalState:
        """
        Reconstruct historical state from a snapshot.

        For now, we use the snapshot as-is. In the future, this could:
        - Apply events between snapshot and timestamp
        - Interpolate state changes
        - Merge with event log
        """
        return HistoricalState(
            saga_id=snapshot.saga_id,
            saga_name=snapshot.saga_name,
            timestamp=timestamp,
            status=snapshot.status,
            context=snapshot.context.copy(),
            completed_steps=snapshot.completed_steps.copy(),
            current_step=snapshot.step_name,
            step_index=snapshot.step_index,
        )
