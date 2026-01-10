# ============================================
# FILE: sagaz/storage/backends/redis/snapshot.py
# ============================================

"""
Redis Snapshot Storage

Redis-based persistent storage for saga snapshots with TTL support,
compression, and distributed caching capabilities.

Requires: pip install redis zstandard
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sagaz.core.exceptions import MissingDependencyError
from sagaz.core.replay import ReplayResult, SagaSnapshot, SnapshotNotFoundError
from sagaz.storage.interfaces.snapshot import SnapshotStorage

try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    REDIS_AVAILABLE = False  # pragma: no cover
    redis: Any = None  # type: ignore[no-redef]  # pragma: no cover

try:
    import zstandard as zstd

    ZSTD_AVAILABLE = True
except ImportError:  # pragma: no cover
    ZSTD_AVAILABLE = False  # pragma: no cover
    zstd = None  # pragma: no cover


class RedisSnapshotStorage(SnapshotStorage):
    """
    Redis implementation of snapshot storage

    Uses Redis for distributed snapshot storage with automatic expiration,
    optional compression, and clustering support.

    Example:
        >>> async with RedisSnapshotStorage("redis://localhost:6379") as storage:
        ...     await storage.save_snapshot(snapshot)
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "snapshot:",
        default_ttl: int | None = None,  # TTL in seconds for snapshots
        enable_compression: bool = True,
        compression_level: int = 3,  # zstd compression level (1-22)
        **redis_kwargs,
    ):
        if not REDIS_AVAILABLE:
            msg = "redis"
            raise MissingDependencyError(msg, "Redis snapshot storage backend")

        if enable_compression and not ZSTD_AVAILABLE:
            msg = "zstandard"
            raise MissingDependencyError(
                msg, "Snapshot compression (install with: pip install zstandard)"
            )

        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.default_ttl = default_ttl
        self.enable_compression = enable_compression and ZSTD_AVAILABLE
        self.compression_level = compression_level
        self.redis_kwargs = redis_kwargs
        self._redis = None
        self._lock = asyncio.Lock()
        self._compressor = (
            zstd.ZstdCompressor(level=compression_level) if self.enable_compression else None
        )
        self._decompressor = zstd.ZstdDecompressor() if self.enable_compression else None

    async def _get_redis(self):
        """Get Redis connection, creating if necessary"""
        if self._redis is None:
            try:
                self._redis = redis.from_url(self.redis_url, **self.redis_kwargs)
                # Test connection
                await self._redis.ping()  # type: ignore[attr-defined]
            except Exception as e:  # pragma: no cover
                msg = f"Failed to connect to Redis: {e}"  # pragma: no cover
                raise ConnectionError(msg)  # pragma: no cover

        return self._redis

    def _snapshot_key(self, snapshot_id: UUID) -> str:
        """Generate Redis key for snapshot"""
        return f"{self.key_prefix}{snapshot_id}"

    def _saga_index_key(self, saga_id: UUID) -> str:
        """Generate Redis key for saga snapshot index (sorted set)"""
        return f"{self.key_prefix}saga:{saga_id}:index"

    def _replay_log_key(self, replay_id: UUID) -> str:
        """Generate Redis key for replay log"""
        return f"{self.key_prefix}replay:{replay_id}"

    def _saga_replays_key(self, saga_id: UUID) -> str:
        """Generate Redis key for saga replays index"""
        return f"{self.key_prefix}saga:{saga_id}:replays"

    def _serialize(self, data: dict[str, Any]) -> bytes:
        """Serialize and optionally compress data"""
        json_bytes = json.dumps(data, default=str).encode("utf-8")

        if self.enable_compression and self._compressor:
            return self._compressor.compress(json_bytes)

        return json_bytes

    def _deserialize(self, data: bytes) -> dict[str, Any]:
        """Decompress and deserialize data"""
        if self.enable_compression and self._decompressor:
            json_bytes = self._decompressor.decompress(data)
        else:
            json_bytes = data

        return json.loads(json_bytes.decode("utf-8"))

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        """Save snapshot to Redis"""
        r = await self._get_redis()

        # Serialize snapshot
        snapshot_data = snapshot.to_dict()
        serialized = self._serialize(snapshot_data)

        # Save snapshot
        key = self._snapshot_key(snapshot.snapshot_id)
        await r.set(key, serialized)  # type: ignore[attr-defined]

        # Set TTL if retention_until is specified
        if snapshot.retention_until:
            ttl_seconds = int((snapshot.retention_until - datetime.now(UTC)).total_seconds())
            if ttl_seconds > 0:
                await r.expire(key, ttl_seconds)  # type: ignore[attr-defined]
        elif self.default_ttl:
            await r.expire(key, self.default_ttl)  # type: ignore[attr-defined]

        # Add to saga index (sorted set by timestamp)
        saga_index = self._saga_index_key(snapshot.saga_id)
        timestamp_score = snapshot.created_at.timestamp()
        await r.zadd(  # type: ignore[attr-defined]
            saga_index, {str(snapshot.snapshot_id): timestamp_score}
        )

    async def get_snapshot(self, snapshot_id: UUID) -> SagaSnapshot | None:
        """Retrieve snapshot by ID"""
        r = await self._get_redis()

        key = self._snapshot_key(snapshot_id)
        data = await r.get(key)  # type: ignore[attr-defined]

        if data is None:
            return None

        snapshot_dict = self._deserialize(data)
        return SagaSnapshot.from_dict(snapshot_dict)

    async def get_latest_snapshot(
        self, saga_id: UUID, before_step: str | None = None
    ) -> SagaSnapshot | None:
        """Get most recent snapshot for saga"""
        r = await self._get_redis()

        # Get all snapshot IDs for this saga (sorted by timestamp DESC)
        saga_index = self._saga_index_key(saga_id)
        snapshot_ids = await r.zrevrange(saga_index, 0, -1)  # type: ignore[attr-defined]

        if not snapshot_ids:
            return None

        # Find matching snapshot
        for snapshot_id_bytes in snapshot_ids:
            snapshot_id = UUID(snapshot_id_bytes.decode("utf-8"))
            snapshot = await self.get_snapshot(snapshot_id)

            if snapshot is None:
                continue

            # Filter by before_step if provided
            if before_step is None or snapshot.step_name == before_step:
                return snapshot

        return None

    async def get_snapshot_at_time(self, saga_id: UUID, timestamp: datetime) -> SagaSnapshot | None:
        """Get snapshot at or before given timestamp"""
        r = await self._get_redis()

        # Get snapshot IDs before timestamp (using sorted set range)
        saga_index = self._saga_index_key(saga_id)
        timestamp_score = timestamp.timestamp()

        # Get all snapshots with score <= timestamp, sorted DESC
        snapshot_ids = await r.zrevrangebyscore(  # type: ignore[attr-defined]
            saga_index, timestamp_score, "-inf", start=0, num=1
        )

        if not snapshot_ids:
            return None

        snapshot_id = UUID(snapshot_ids[0].decode("utf-8"))
        return await self.get_snapshot(snapshot_id)

    async def list_snapshots(self, saga_id: UUID, limit: int = 100) -> list[SagaSnapshot]:
        """List all snapshots for saga"""
        r = await self._get_redis()

        # Get snapshot IDs (sorted by timestamp DESC)
        saga_index = self._saga_index_key(saga_id)
        snapshot_ids = await r.zrevrange(saga_index, 0, limit - 1)  # type: ignore[attr-defined]

        # Fetch all snapshots
        snapshots = []
        for snapshot_id_bytes in snapshot_ids:
            snapshot_id = UUID(snapshot_id_bytes.decode("utf-8"))
            snapshot = await self.get_snapshot(snapshot_id)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    async def delete_snapshot(self, snapshot_id: UUID) -> bool:
        """Delete snapshot"""
        r = await self._get_redis()

        # Get snapshot to find saga_id
        snapshot = await self.get_snapshot(snapshot_id)
        if snapshot is None:
            return False

        # Delete snapshot
        key = self._snapshot_key(snapshot_id)
        deleted = await r.delete(key)  # type: ignore[attr-defined]

        # Remove from saga index
        saga_index = self._saga_index_key(snapshot.saga_id)
        await r.zrem(saga_index, str(snapshot_id))  # type: ignore[attr-defined]

        return deleted > 0

    async def delete_expired_snapshots(self) -> int:
        """
        Delete expired snapshots

        Note: Redis automatically handles TTL expiration,
        so this is mainly for cleanup of index entries.
        """
        # Redis handles TTL automatically, but we can clean up orphaned index entries
        # This is optional and can be implemented with a background job
        return 0

    async def save_replay_log(self, replay_result: ReplayResult) -> None:
        """Save replay log"""
        r = await self._get_redis()

        # Serialize replay log
        replay_data = replay_result.to_dict()
        serialized = self._serialize(replay_data)

        # Save replay log
        key = self._replay_log_key(replay_result.replay_id)
        await r.set(key, serialized)  # type: ignore[attr-defined]

        if self.default_ttl:
            await r.expire(key, self.default_ttl)  # type: ignore[attr-defined]

        # Add to saga replays index
        replays_index = self._saga_replays_key(replay_result.original_saga_id)
        timestamp_score = replay_result.created_at.timestamp()
        await r.zadd(  # type: ignore[attr-defined]
            replays_index, {str(replay_result.replay_id): timestamp_score}
        )

    async def get_replay_log(self, replay_id: UUID) -> dict[str, Any] | None:
        """Get replay log entry"""
        r = await self._get_redis()

        key = self._replay_log_key(replay_id)
        data = await r.get(key)  # type: ignore[attr-defined]

        if data is None:
            return None

        return self._deserialize(data)

    async def list_replays(self, original_saga_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        """List replays for original saga"""
        r = await self._get_redis()

        # Get replay IDs (sorted by timestamp DESC)
        replays_index = self._saga_replays_key(original_saga_id)
        replay_ids = await r.zrevrange(replays_index, 0, limit - 1)  # type: ignore[attr-defined]

        # Fetch all replay logs
        replays = []
        for replay_id_bytes in replay_ids:
            replay_id = UUID(replay_id_bytes.decode("utf-8"))
            replay = await self.get_replay_log(replay_id)
            if replay:
                replays.append(replay)

        return replays

    async def close(self) -> None:
        """Close Redis connection"""
        if self._redis:
            await self._redis.close()  # type: ignore[attr-defined]
            await self._redis.connection_pool.disconnect()  # type: ignore[attr-defined]
            self._redis = None

    async def __aenter__(self):
        """Context manager entry"""
        await self._get_redis()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.close()
