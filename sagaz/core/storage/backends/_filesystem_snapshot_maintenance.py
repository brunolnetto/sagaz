"""Expiry cleanup and storage statistics for :class:`FilesystemSnapshotStorage`."""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID


class _FilesystemSnapshotMaintenanceMixin:
    """Retention cleanup, per-saga cleanup and directory statistics."""

    base_path: Path
    enable_compression: bool
    snapshots_dir: Path
    replays_dir: Path

    if TYPE_CHECKING:

        def _get_index_path(self, saga_id: UUID) -> Path: ...

        async def _read_json(self, path: Path) -> dict[str, Any]: ...

        async def delete_snapshot(self, snapshot_id: UUID) -> bool: ...

    async def delete_expired_snapshots(self) -> int:
        """Delete expired snapshots based on retention_until"""
        now = datetime.now(UTC)
        deleted_count = 0

        # Scan all saga directories
        for saga_dir in self.snapshots_dir.iterdir():
            if not saga_dir.is_dir():
                continue

            for snapshot_file in saga_dir.iterdir():
                if not snapshot_file.is_file():
                    continue

                try:
                    snapshot_data = await self._read_json(snapshot_file)
                    retention_until = snapshot_data.get("retention_until")

                    if retention_until:
                        retention_dt = datetime.fromisoformat(retention_until)
                        if retention_dt < now:
                            # Expired - delete
                            snapshot_id = UUID(snapshot_data["snapshot_id"])
                            if await self.delete_snapshot(snapshot_id):
                                deleted_count += 1
                except Exception:
                    # Skip corrupted files
                    continue

        return deleted_count

    def get_storage_info(self) -> dict[str, Any]:
        """Get storage statistics and info"""
        total_snapshots = 0
        total_size = 0
        saga_count = 0

        # Count snapshots and size
        for saga_dir in self.snapshots_dir.iterdir():
            if not saga_dir.is_dir():
                continue

            saga_count += 1
            for snapshot_file in saga_dir.iterdir():
                if snapshot_file.is_file():
                    total_snapshots += 1
                    total_size += snapshot_file.stat().st_size

        # Count replays
        replay_count = len(list(self.replays_dir.iterdir()))

        return {
            "storage_type": "filesystem",
            "base_path": str(self.base_path.absolute()),
            "compression_enabled": self.enable_compression,
            "total_sagas": saga_count,
            "total_snapshots": total_snapshots,
            "total_replays": replay_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

    async def cleanup_saga(self, saga_id: UUID) -> int:
        """
        Delete all snapshots for a saga.

        Useful for development cleanup.

        Returns:
            Number of snapshots deleted
        """
        saga_dir = self.snapshots_dir / str(saga_id)
        if not saga_dir.exists():
            return 0

        deleted = len(list(saga_dir.iterdir()))

        # Delete saga directory
        shutil.rmtree(saga_dir)

        # Delete index
        index_path = self._get_index_path(saga_id)
        if index_path.exists():
            index_path.unlink()

        return deleted
