"""
Redis storage implementation for saga state

Provides Redis-based persistent storage for saga state with support for
clustering, replication, and automatic expiration of completed sagas.

Requires: pip install redis
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sagaz.core.exceptions import MissingDependencyError
from sagaz.storage.base import (
    SagaNotFoundError,
    SagaStorage,
    SagaStorageConnectionError,
    SagaStorageError,
)
from sagaz.core.types import SagaStatus, SagaStepStatus

try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    REDIS_AVAILABLE = False  # pragma: no cover
    redis: Any = None  # type: ignore[no-redef]  # pragma: no cover


class RedisSagaStorage(SagaStorage):
    """
    Redis implementation of saga storage

    Uses Redis for persistent, distributed saga state storage.
    Supports automatic cleanup and clustering.

    Example:
        >>> async with RedisSagaStorage("redis://localhost:6379") as storage:
        ...     await storage.save_saga_state(
        ...         saga_id="order-123",
        ...         saga_name="OrderSaga",
        ...         status=SagaStatus.EXECUTING,
        ...         steps=[],
        ...         context={"order_id": "ABC123"}
        ...     )
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "saga:",
        default_ttl: int | None = None,  # TTL in seconds for completed sagas
        **redis_kwargs,
    ):
        if not REDIS_AVAILABLE:
            msg = "redis"
            raise MissingDependencyError(msg, "Redis storage backend")

        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.default_ttl = default_ttl
        self.redis_kwargs = redis_kwargs
        self._redis = None
        self._lock = asyncio.Lock()

    async def _get_redis(self):
        """Get Redis connection, creating if necessary"""
        if self._redis is None:
            try:
                self._redis = redis.from_url(self.redis_url, **self.redis_kwargs)
                # Test connection
                await self._redis.ping()  # type: ignore[attr-defined]
            except Exception as e:  # pragma: no cover
                msg = f"Failed to connect to Redis: {e}"  # pragma: no cover
                raise SagaStorageConnectionError(msg)  # pragma: no cover

        return self._redis

    def _saga_key(self, saga_id: str) -> str:
        """Generate Redis key for saga"""
        return f"{self.key_prefix}{saga_id}"

    def _step_key(self, saga_id: str, step_name: str) -> str:
        """Generate Redis key for step"""
        return f"{self.key_prefix}{saga_id}:step:{step_name}"

    def _index_key(self, index_type: str) -> str:
        """Generate Redis key for indexes"""
        return f"{self.key_prefix}index:{index_type}"

    async def save_saga_state(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save saga state to Redis"""

        redis_client = await self._get_redis()

        saga_data = {
            "saga_id": saga_id,
            "saga_name": saga_name,
            "status": status.value,
            "steps": steps,
            "context": context,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        saga_key = self._saga_key(saga_id)

        # Use pipeline for atomic operations
        async with redis_client.pipeline() as pipe:
            # Store saga data
            await pipe.hset(saga_key, mapping={"data": json.dumps(saga_data, default=str)})

            # Add to status index
            status_index = self._index_key(f"status:{status.value}")
            await pipe.sadd(status_index, saga_id)

            # Add to name index
            name_index = self._index_key(f"name:{saga_name}")
            await pipe.sadd(name_index, saga_id)

            # Set TTL for completed sagas
            if self.default_ttl and status in [SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK]:
                await pipe.expire(saga_key, self.default_ttl)

            await pipe.execute()

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """Load saga state from Redis"""

        redis_client = await self._get_redis()
        saga_key = self._saga_key(saga_id)

        saga_data_json = await redis_client.hget(saga_key, "data")
        if not saga_data_json:
            return None

        try:
            return json.loads(saga_data_json)  # type: ignore[no-any-return]
        except json.JSONDecodeError as e:  # pragma: no cover
            msg = f"Failed to decode saga data for {saga_id}: {e}"  # pragma: no cover
            raise SagaStorageError(msg)  # pragma: no cover

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state from Redis"""

        redis_client = await self._get_redis()

        # First load the saga to get its status and name for index cleanup
        saga_data = await self.load_saga_state(saga_id)
        if not saga_data:
            return False

        saga_key = self._saga_key(saga_id)

        async with redis_client.pipeline() as pipe:
            # Delete main saga data
            await pipe.delete(saga_key)

            # Remove from indexes
            status_index = self._index_key(f"status:{saga_data['status']}")
            await pipe.srem(status_index, saga_id)

            name_index = self._index_key(f"name:{saga_data['saga_name']}")
            await pipe.srem(name_index, saga_id)

            result = await pipe.execute()

        return result[0] > 0  # type: ignore[no-any-return]  # First command (delete) returns count

    async def list_sagas(
        self,
        status: SagaStatus | None = None,
        saga_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List sagas with filtering"""

        redis_client = await self._get_redis()
        saga_ids = await self._get_filtered_saga_ids(redis_client, status, saga_name)

        # Apply pagination
        saga_id_list = list(saga_ids)[offset : offset + limit]

        # Load and build summaries
        results = await self._build_saga_summaries(saga_id_list)

        # Sort by created_at (newest first)
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results

    async def _get_filtered_saga_ids(
        self, redis_client, status: SagaStatus | None, saga_name: str | None
    ) -> set:
        """Get saga IDs matching filters."""
        saga_ids = await self._get_ids_by_status(redis_client, status) if status else set()
        saga_ids = await self._apply_name_filter(redis_client, saga_ids, saga_name)
        return saga_ids or await self._get_all_saga_ids(redis_client)

    async def _apply_name_filter(
        self, redis_client, current_ids: set, saga_name: str | None
    ) -> set:
        """Apply name filter to saga IDs."""
        if not saga_name:
            return current_ids
        name_ids = await self._get_ids_by_name(redis_client, saga_name)
        return current_ids.intersection(name_ids) if current_ids else name_ids

    async def _get_ids_by_status(self, redis_client, status: SagaStatus) -> set:
        """Get saga IDs by status."""
        status_index = self._index_key(f"status:{status.value}")
        status_ids = await redis_client.smembers(status_index)
        return {s.decode() if isinstance(s, bytes) else s for s in status_ids}

    async def _get_ids_by_name(self, redis_client, saga_name: str) -> set:
        """Get saga IDs by name."""
        name_index = self._index_key(f"name:{saga_name}")
        name_ids = await redis_client.smembers(name_index)
        return {s.decode() if isinstance(s, bytes) else s for s in name_ids}

    async def _get_all_saga_ids(self, redis_client) -> set:
        """Get all saga IDs (no filters)."""
        pattern = f"{self.key_prefix}*"
        keys = await redis_client.keys(pattern)
        return {
            key.decode().replace(self.key_prefix, "")
            for key in keys
            if ":step:" not in key.decode() and ":index:" not in key.decode()
        }

    async def _build_saga_summaries(self, saga_id_list: list[str]) -> list[dict[str, Any]]:
        """Build summary objects for saga IDs."""
        results = []
        for saga_id in saga_id_list:
            saga_data = await self.load_saga_state(saga_id)
            if saga_data:
                results.append(self._create_saga_summary(saga_data))
        return results

    def _create_saga_summary(self, saga_data: dict[str, Any]) -> dict[str, Any]:
        """Create summary dict from saga data."""
        return {
            "saga_id": saga_data["saga_id"],
            "saga_name": saga_data["saga_name"],
            "status": saga_data["status"],
            "created_at": saga_data["created_at"],
            "updated_at": saga_data["updated_at"],
            "step_count": len(saga_data["steps"]),
            "completed_steps": sum(
                1
                for step in saga_data["steps"]
                if step.get("status") == SagaStepStatus.COMPLETED.value
            ),
        }

    async def update_step_state(
        self,
        saga_id: str,
        step_name: str,
        status: SagaStepStatus,
        result: Any = None,
        error: str | None = None,
        executed_at: datetime | None = None,
    ) -> None:
        """Update individual step state"""
        saga_data = await self.load_saga_state(saga_id)
        if not saga_data:
            msg = f"Saga {saga_id} not found"
            raise SagaNotFoundError(msg)

        if not self._update_step_in_data(saga_data, step_name, status, result, error, executed_at):
            msg = f"Step {step_name} not found in saga {saga_id}"
            raise SagaStorageError(msg)

        saga_data["updated_at"] = datetime.now(UTC).isoformat()
        await self._save_updated_saga(saga_data)

    def _update_step_in_data(
        self,
        saga_data: dict,
        step_name: str,
        status: SagaStepStatus,
        result: Any,
        error: str | None,
        executed_at: datetime | None,
    ) -> bool:
        """Update step data in saga. Returns True if step was found."""
        for step in saga_data["steps"]:
            if step["name"] == step_name:
                step["status"] = status.value
                step["result"] = result
                step["error"] = error
                if executed_at:
                    step["executed_at"] = executed_at.isoformat()
                return True
        return False

    async def _save_updated_saga(self, saga_data: dict) -> None:
        """Save updated saga state."""
        await self.save_saga_state(
            saga_id=saga_data["saga_id"],
            saga_name=saga_data["saga_name"],
            status=SagaStatus(saga_data["status"]),
            steps=saga_data["steps"],
            context=saga_data["context"],
            metadata=saga_data["metadata"],
        )

    async def get_saga_statistics(self) -> dict[str, Any]:
        """Get storage statistics"""

        redis_client = await self._get_redis()

        # Get memory info
        memory_info = await redis_client.info("memory")

        # Count sagas by status
        status_counts = {}
        for status in SagaStatus:
            status_index = self._index_key(f"status:{status.value}")
            count = await redis_client.scard(status_index)
            status_counts[status.value] = count

        total_sagas = sum(status_counts.values())

        return {
            "total_sagas": total_sagas,
            "by_status": status_counts,
            "redis_memory_usage": memory_info.get("used_memory", 0),
            "redis_memory_human": memory_info.get("used_memory_human", "0B"),
        }

    async def cleanup_completed_sagas(
        self, older_than: datetime, statuses: list[SagaStatus] | None = None
    ) -> int:
        """Clean up old completed sagas"""
        if statuses is None:
            statuses = [SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK]

        redis_client = await self._get_redis()
        deleted_count = 0

        for status in statuses:
            deleted_count += await self._cleanup_sagas_by_status(redis_client, status, older_than)

        return deleted_count

    async def _cleanup_sagas_by_status(
        self, redis_client, status: SagaStatus, older_than: datetime
    ) -> int:
        """Clean up sagas with a specific status."""
        saga_ids = await self._get_saga_ids_by_status(redis_client, status)
        return await self._delete_old_sagas(saga_ids, older_than)

    async def _get_saga_ids_by_status(self, redis_client, status: SagaStatus) -> list[str]:
        """Get decoded saga IDs for a status."""
        status_index = self._index_key(f"status:{status.value}")
        saga_ids = await redis_client.smembers(status_index)
        return [s.decode() if isinstance(s, bytes) else s for s in saga_ids]

    async def _delete_old_sagas(self, saga_ids: list[str], older_than: datetime) -> int:
        """Delete sagas that are older than the given datetime."""
        deleted = 0
        for saga_id in saga_ids:
            if await self._should_delete_saga(saga_id, older_than):
                deleted += await self._try_delete_saga(saga_id)
        return deleted

    async def _try_delete_saga(self, saga_id: str) -> int:
        """Try to delete a saga, returning 1 if successful, 0 otherwise."""
        return 1 if await self.delete_saga_state(saga_id) else 0

    async def _should_delete_saga(self, saga_id: str, older_than: datetime) -> bool:
        """Check if a saga should be deleted based on age."""
        saga_data = await self.load_saga_state(saga_id)
        if not saga_data:
            return False
        return self._is_saga_older_than(saga_data, older_than)

    def _is_saga_older_than(self, saga_data: dict, older_than: datetime) -> bool:
        """Check if saga data is older than the given datetime."""
        try:
            updated_at = datetime.fromisoformat(saga_data["updated_at"])
            return updated_at < older_than
        except (ValueError, KeyError):
            return False

    async def health_check(self) -> dict[str, Any]:
        """Check storage health"""

        try:
            redis_client = await self._get_redis()

            # Test basic operations
            test_key = f"{self.key_prefix}health_check"
            await redis_client.set(test_key, "ok", ex=10)  # Expire in 10 seconds
            result = await redis_client.get(test_key)
            await redis_client.delete(test_key)

            if result != b"ok":  # pragma: no cover
                msg = "Read/write test failed"  # pragma: no cover
                raise Exception(msg)  # pragma: no cover

            # Get Redis info
            info = await redis_client.info()

            return {
                "status": "healthy",
                "storage_type": "redis",
                "redis_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "0B"),
                "timestamp": datetime.now(UTC).isoformat(),
            }

        except Exception as e:  # pragma: no cover
            return {
                "status": "unhealthy",
                "storage_type": "redis",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }  # pragma: no cover

    async def close(self):
        """Close connection explicitly."""
        if self._redis:
            await self._redis.aclose()

    async def __aenter__(self):
        """Async context manager entry"""
        await self._get_redis()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def count(self) -> int:  # pragma: no cover
        """Count total sagas."""
        redis_client = await self._get_redis()
        # This is expensive in Redis, better use a counter key or scan
        # For simplicity in this tool, using scan loop or keys
        # Keys approach (not recommended for prod but ok/common for smaller setups)
        # Better: sum of status set cardinalities
        count = 0
        for status in SagaStatus:
             status_index = self._index_key(f"status:{status.value}")
             count += await redis_client.scard(status_index)
        return count

    async def export_all(self):  # pragma: no cover
        """Export all records for transfer."""
        redis_client = await self._get_redis()
        saga_ids = await self._get_all_saga_ids(redis_client)

        for saga_id in sorted(saga_ids):
            saga_data = await self.load_saga_state(saga_id)
            if saga_data:
                yield saga_data

    async def import_record(self, record: dict[str, Any]) -> None:  # pragma: no cover
        """Import a single record from transfer."""
        await self.save_saga_state(
            saga_id=record["saga_id"],
            saga_name=record["saga_name"],
            status=SagaStatus(record["status"]),
            steps=record.get("steps", []),
            context=record.get("context", {}),
            metadata=record.get("metadata"),
        )
