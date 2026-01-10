# ============================================
# FILE: sagaz/storage/backends/memory_snapshot.py
# ============================================

"""
In-Memory Snapshot Storage

Simple in-memory implementation for testing and development.
Not suitable for production use.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sagaz.core.replay import ReplayResult, SagaSnapshot, SnapshotNotFoundError
from sagaz.storage.interfaces.snapshot import SnapshotStorage


class InMemorySnapshotStorage(SnapshotStorage):
    """In-memory implementation of snapshot storage"""

    def __init__(self):
        self._snapshots: dict[UUID, SagaSnapshot] = {}
        self._saga_snapshots: dict[UUID, list[UUID]] = {}  # saga_id -> [snapshot_ids]
        self._replay_logs: dict[UUID, dict[str, Any]] = {}

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Save snapshot to memory"""
        self._snapshots[snapshot.snapshot_id] = snapshot

        # Track by saga_id
        if snapshot.saga_id not in self._saga_snapshots:
            self._saga_snapshots[snapshot.saga_id] = []
        self._saga_snapshots[snapshot.saga_id].append(snapshot.snapshot_id)

    async def get_snapshot(self, snapshot_id: UUID) -> SagaSnapshot | None:
        """Retrieve snapshot by ID"""
        return self._snapshots.get(snapshot_id)

    async def get_latest_snapshot(
        self, saga_id: UUID, before_step: str | None = None
    ) -> SagaSnapshot | None:
        """
        Get most recent snapshot for saga, optionally before a specific step.

        Args:
            saga_id: The saga ID
            before_step: If provided, get snapshot at or before this step name

        Returns:
            Most recent snapshot matching criteria, or None
        """
        snapshot_ids = self._saga_snapshots.get(saga_id, [])
        if not snapshot_ids:
            return None

        # Get all snapshots for this saga
        snapshots = [self._snapshots[sid] for sid in snapshot_ids]

        # If before_step specified, find snapshot at or before that step
        if before_step:
            # Find step with matching name (could be multiple with retries)
            matching = [s for s in snapshots if s.step_name == before_step]
            if matching:
                # Return the most recent one
                return max(matching, key=lambda s: s.created_at)
            # No exact match, return None (checkpoint not found)
            return None

        # No filter, return most recent overall
        return max(snapshots, key=lambda s: s.created_at)

    async def get_snapshot_at_time(self, saga_id: UUID, timestamp: datetime) -> SagaSnapshot | None:
        """Get snapshot at or before given timestamp"""
        snapshot_ids = self._saga_snapshots.get(saga_id, [])
        if not snapshot_ids:
            return None

        # Get snapshots before timestamp
        snapshots = [
            self._snapshots[sid]
            for sid in snapshot_ids
            if self._snapshots[sid].created_at <= timestamp
        ]

        if not snapshots:
            return None

        # Return closest to timestamp
        return max(snapshots, key=lambda s: s.created_at)

    async def list_snapshots(self, saga_id: UUID, limit: int = 100) -> list[SagaSnapshot]:
        """List all snapshots for saga"""
        snapshot_ids = self._saga_snapshots.get(saga_id, [])
        snapshots = [self._snapshots[sid] for sid in snapshot_ids]

        # Sort by created_at DESC
        snapshots.sort(key=lambda s: s.created_at, reverse=True)

        return snapshots[:limit]

    async def delete_snapshot(self, snapshot_id: UUID) -> bool:
        """Delete snapshot"""
        if snapshot_id not in self._snapshots:
            return False

        snapshot = self._snapshots[snapshot_id]
        del self._snapshots[snapshot_id]

        # Remove from saga index
        if snapshot.saga_id in self._saga_snapshots:
            self._saga_snapshots[snapshot.saga_id].remove(snapshot_id)

        return True

    async def delete_expired_snapshots(self) -> int:
        """Delete expired snapshots"""
        now = datetime.now(UTC)
        expired = [
            sid
            for sid, snapshot in self._snapshots.items()
            if snapshot.retention_until and snapshot.retention_until < now
        ]

        for sid in expired:
            await self.delete_snapshot(sid)

        return len(expired)

    async def save_replay_log(self, replay_result: ReplayResult) -> None:
        """Save replay log"""
        self._replay_logs[replay_result.replay_id] = replay_result.to_dict()

    async def get_replay_log(self, replay_id: UUID) -> dict[str, Any] | None:
        """Get replay log entry"""
        return self._replay_logs.get(replay_id)

    async def list_replays(self, original_saga_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        """List replays for original saga"""
        replays = [
            log
            for log in self._replay_logs.values()
            if UUID(log["original_saga_id"]) == original_saga_id
        ]

        # Sort by created_at DESC
        replays.sort(key=lambda r: r["created_at"], reverse=True)

        return replays[:limit]

    def clear(self) -> None:
        """Clear all data (useful for testing)"""
        self._snapshots.clear()
        self._saga_snapshots.clear()
        self._replay_logs.clear()
