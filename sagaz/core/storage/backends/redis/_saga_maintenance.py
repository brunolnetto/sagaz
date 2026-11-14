"""Statistics, cleanup and health checks for :class:`RedisSagaStorage`."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sagaz.core.storage._reserved import is_reserved_saga_name
from sagaz.core.storage.backends.redis._saga_tenancy import _RedisSagaTenancyMixin
from sagaz.core.tenant import is_system_scope
from sagaz.core.types import SagaStatus


class _RedisSagaMaintenanceMixin(_RedisSagaTenancyMixin):
    """Status counters, retention cleanup and health probing.

    In the system scope, statistics, counts and cleanup cover every tenant.
    """

    if TYPE_CHECKING:

        def _index_key(self, index_type: str) -> str: ...

        async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None: ...

        async def delete_saga_state(self, saga_id: str) -> bool: ...

    async def get_saga_statistics(self) -> dict[str, Any]:
        """Get storage statistics"""
        if is_system_scope():
            return self._merge_statistics(await self._for_each_tenant(self.get_saga_statistics))

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

    @staticmethod
    def _merge_statistics(per_tenant: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        """Add up the per-tenant statistics (Redis memory figures are server-wide)."""
        merged = dict(per_tenant[0][1])
        by_status = {status.value: 0 for status in SagaStatus}
        for _, stats in per_tenant:
            for status, count in stats["by_status"].items():
                by_status[status] += count
        merged["by_status"] = by_status
        merged["total_sagas"] = sum(by_status.values())
        return merged

    async def cleanup_completed_sagas(
        self, older_than: datetime, statuses: list[SagaStatus] | None = None
    ) -> int:
        """Clean up old completed sagas"""
        if is_system_scope():
            results = await self._for_each_tenant(
                self.cleanup_completed_sagas, older_than, statuses
            )
            return sum(deleted for _, deleted in results)
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
        if not saga_data or is_reserved_saga_name(saga_data.get("saga_name")):
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

            if result != b"ok":
                msg = "Read/write test failed"
                raise RuntimeError(msg)

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

        except Exception as e:
            return {
                "status": "unhealthy",
                "storage_type": "redis",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    async def count(self) -> int:
        """Count total sagas."""
        if is_system_scope():
            return sum(count for _, count in await self._for_each_tenant(self.count))
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
