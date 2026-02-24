# ============================================
# FILE: sagaz/storage/backends/filesystem_snapshot.py
# ============================================

"""
Filesystem Snapshot Storage

Local filesystem implementation for development, testing, and research.
Stores snapshots as JSON files in a directory structure.

Features:
- JSON serialization for human readability
- Organized directory structure (saga_id/snapshot_id.json)
- Optional compression (gzip)
- Replay log storage
- TTL-based cleanup

**Not recommended for production** - Use S3/PostgreSQL/Redis instead.

Example:
    >>> storage = FilesystemSnapshotStorage(
    ...     base_path="/tmp/saga-snapshots",
    ...     enable_compression=True
    ... )
    >>> async with storage:
    ...     await storage.save_snapshot(snapshot)
"""

import asyncio
import gzip
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import aiofiles

from sagaz.core.replay import ReplayResult, SagaSnapshot
from sagaz.storage.interfaces.snapshot import SnapshotStorage


class FilesystemSnapshotStorage(SnapshotStorage):
    """
    Filesystem-based snapshot storage for local development.

    Stores snapshots in a directory structure:
        base_path/
        ├── snapshots/
        │   ├── {saga_id}/
        │   │   ├── {snapshot_id}.json[.gz]
        │   │   └── ...
        │   └── ...
        ├── indexes/
        │   └── {saga_id}.json  # List of snapshot IDs with timestamps
        └── replays/
            └── {replay_id}.json

    Example:
        >>> storage = FilesystemSnapshotStorage(
        ...     base_path="./dev-snapshots",
        ...     enable_compression=True
        ... )
        >>> await storage.save_snapshot(snapshot)
    """

    def __init__(
        self,
        base_path: str = "./saga-snapshots",
        enable_compression: bool = False,
        pretty_json: bool = True,
    ):
        """
        Initialize filesystem snapshot storage.

        Args:
            base_path: Root directory for snapshots (default: ./saga-snapshots)
            enable_compression: Enable gzip compression for JSON files
            pretty_json: Pretty-print JSON for readability (indent=2)
        """
        self.base_path = Path(base_path)
        self.enable_compression = enable_compression
        self.pretty_json = pretty_json

        # Create directory structure
        self.snapshots_dir = self.base_path / "snapshots"
        self.indexes_dir = self.base_path / "indexes"
        self.replays_dir = self.base_path / "replays"

        # Create directories on init (sync)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.indexes_dir.mkdir(parents=True, exist_ok=True)
        self.replays_dir.mkdir(parents=True, exist_ok=True)

        self._lock = asyncio.Lock()

    def _get_snapshot_path(self, saga_id: UUID, snapshot_id: UUID) -> Path:
        """Get path for snapshot file"""
        saga_dir = self.snapshots_dir / str(saga_id)
        saga_dir.mkdir(exist_ok=True)

        suffix = ".json.gz" if self.enable_compression else ".json"
        return saga_dir / f"{snapshot_id}{suffix}"

    def _get_index_path(self, saga_id: UUID) -> Path:
        """Get path for saga index file"""
        return self.indexes_dir / f"{saga_id}.json"

    def _get_replay_path(self, replay_id: UUID) -> Path:
        """Get path for replay log file"""
        return self.replays_dir / f"{replay_id}.json"

    async def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        """Write JSON data to file with optional compression"""
        json_str = json.dumps(
            data, default=str, indent=2 if self.pretty_json else None
        )

        if self.enable_compression:
            # Write compressed
            compressed = gzip.compress(json_str.encode("utf-8"))
            async with aiofiles.open(path, "wb") as f:
                await f.write(compressed)
        else:
            # Write plain JSON
            async with aiofiles.open(path, "w") as f:
                await f.write(json_str)

    async def _read_json(self, path: Path) -> dict[str, Any]:
        """Read JSON data from file with optional decompression"""
        if not path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {path}")

        if self.enable_compression or path.suffix == ".gz":
            # Read compressed
            async with aiofiles.open(path, "rb") as f:
                compressed = await f.read()
            json_str = gzip.decompress(compressed).decode("utf-8")
        else:
            # Read plain JSON
            async with aiofiles.open(path, "r") as f:
                json_str = await f.read()

        return json.loads(json_str)

    async def _update_index(self, saga_id: UUID, snapshot_id: UUID, created_at: datetime) -> None:
        """Update saga index with new snapshot"""
        async with self._lock:
            index_path = self._get_index_path(saga_id)

            # Load existing index
            if index_path.exists():
                index_data = await self._read_json(index_path)
            else:
                index_data = {"saga_id": str(saga_id), "snapshots": []}

            # Add new snapshot
            index_data["snapshots"].append(
                {
                    "snapshot_id": str(snapshot_id),
                    "created_at": created_at.isoformat(),
                }
            )

            # Sort by created_at DESC
            index_data["snapshots"].sort(
                key=lambda x: x["created_at"], reverse=True
            )

            # Save index
            await self._write_json(index_path, index_data)

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """
        Save snapshot to filesystem.

        Creates a JSON file at: snapshots/{saga_id}/{snapshot_id}.json[.gz]
        Updates index at: indexes/{saga_id}.json
        """
        snapshot_path = self._get_snapshot_path(snapshot.saga_id, snapshot.snapshot_id)
        snapshot_data = snapshot.to_dict()

        # Write snapshot file
        await self._write_json(snapshot_path, snapshot_data)

        # Update index
        await self._update_index(
            snapshot.saga_id, snapshot.snapshot_id, snapshot.created_at
        )

    async def get_snapshot(self, snapshot_id: UUID) -> SagaSnapshot | None:
        """
        Retrieve snapshot by ID.

        Note: Requires scanning all saga directories since we don't know saga_id.
        For better performance, use get_latest_snapshot() which uses the index.
        """
        # Scan all saga directories
        for saga_dir in self.snapshots_dir.iterdir():
            if not saga_dir.is_dir():
                continue

            # Try both extensions
            for suffix in [".json.gz", ".json"]:
                snapshot_path = saga_dir / f"{snapshot_id}{suffix}"
                if snapshot_path.exists():
                    try:
                        snapshot_data = await self._read_json(snapshot_path)
                        return SagaSnapshot.from_dict(snapshot_data)
                    except Exception:
                        continue

        return None

    async def get_latest_snapshot(
        self, saga_id: UUID, before_step: str | None = None
    ) -> SagaSnapshot | None:
        """Get most recent snapshot for saga"""
        index_path = self._get_index_path(saga_id)
        if not index_path.exists():
            return None

        index_data = await self._read_json(index_path)

        # Iterate through snapshots (already sorted DESC)
        for entry in index_data.get("snapshots", []):
            snapshot_id = UUID(entry["snapshot_id"])
            snapshot = await self.get_snapshot(snapshot_id)

            if snapshot is None:
                continue

            # Filter by before_step if provided
            if before_step is None or snapshot.step_name == before_step:
                return snapshot

        return None

    async def get_snapshot_at_time(
        self, saga_id: UUID, timestamp: datetime
    ) -> SagaSnapshot | None:
        """Get snapshot at or before given timestamp"""
        index_path = self._get_index_path(saga_id)
        if not index_path.exists():
            return None

        index_data = await self._read_json(index_path)

        # Find closest snapshot before timestamp
        target_snapshot = None
        for entry in index_data.get("snapshots", []):
            entry_time = datetime.fromisoformat(entry["created_at"])
            if entry_time <= timestamp:
                snapshot_id = UUID(entry["snapshot_id"])
                target_snapshot = await self.get_snapshot(snapshot_id)
                break

        return target_snapshot

    async def list_snapshots(self, saga_id: UUID, limit: int = 100) -> list[SagaSnapshot]:
        """List all snapshots for saga"""
        index_path = self._get_index_path(saga_id)
        if not index_path.exists():
            return []

        index_data = await self._read_json(index_path)

        # Fetch snapshots (already sorted DESC in index)
        snapshots = []
        for entry in index_data.get("snapshots", [])[:limit]:
            snapshot_id = UUID(entry["snapshot_id"])
            snapshot = await self.get_snapshot(snapshot_id)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    async def delete_snapshot(self, snapshot_id: UUID) -> bool:
        """Delete snapshot"""
        # Find and delete snapshot file
        for saga_dir in self.snapshots_dir.iterdir():
            if not saga_dir.is_dir():
                continue

            for suffix in [".json.gz", ".json"]:
                snapshot_path = saga_dir / f"{snapshot_id}{suffix}"
                if snapshot_path.exists():
                    # Get saga_id before deleting
                    snapshot_data = await self._read_json(snapshot_path)
                    saga_id = UUID(snapshot_data["saga_id"])

                    # Delete file
                    snapshot_path.unlink()

                    # Remove from index
                    await self._remove_from_index(saga_id, snapshot_id)

                    return True

        return False

    async def _remove_from_index(self, saga_id: UUID, snapshot_id: UUID) -> None:
        """Remove snapshot from saga index"""
        async with self._lock:
            index_path = self._get_index_path(saga_id)
            if not index_path.exists():
                return

            index_data = await self._read_json(index_path)

            # Remove snapshot
            index_data["snapshots"] = [
                entry
                for entry in index_data["snapshots"]
                if entry["snapshot_id"] != str(snapshot_id)
            ]

            # Save index
            await self._write_json(index_path, index_data)

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

    async def save_replay_log(self, replay_result: ReplayResult) -> None:
        """Save replay log"""
        replay_path = self._get_replay_path(replay_result.replay_id)
        await self._write_json(replay_path, replay_result.to_dict())

    async def get_replay_log(self, replay_id: UUID) -> dict[str, Any] | None:
        """Get replay log entry"""
        replay_path = self._get_replay_path(replay_id)
        if not replay_path.exists():
            return None

        return await self._read_json(replay_path)

    async def list_replays(
        self, original_saga_id: UUID, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List replays for original saga"""
        replays = []

        # Scan all replay files
        for replay_file in self.replays_dir.iterdir():
            if not replay_file.is_file():
                continue

            try:
                replay_data = await self._read_json(replay_file)
                if UUID(replay_data["original_saga_id"]) == original_saga_id:
                    replays.append(replay_data)
            except Exception:
                continue

        # Sort by created_at DESC
        replays.sort(key=lambda r: r.get("created_at", ""), reverse=True)

        return replays[:limit]

    async def close(self) -> None:
        """Close storage (no-op for filesystem)"""
        pass

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

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
