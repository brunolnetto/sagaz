"""Index lookups and list summaries for :class:`RedisSagaStorage`."""

from typing import TYPE_CHECKING, Any

from sagaz.core.types import SagaStatus, SagaStepStatus


class _RedisSagaQueryMixin:
    """Resolves saga IDs from the status/name indexes and builds summaries."""

    key_prefix: str

    if TYPE_CHECKING:

        def _index_key(self, index_type: str) -> str: ...

        async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None: ...

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
