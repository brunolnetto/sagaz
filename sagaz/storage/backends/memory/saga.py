"""
In-memory storage implementation for saga state

Provides a simple in-memory storage backend for development and testing.
Not suitable for production use as state is lost on process restart.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from sagaz.storage.base import SagaStorage, SagaStorageError
from sagaz.types import SagaStatus, SagaStepStatus


class InMemorySagaStorage(SagaStorage):
    """
    In-memory implementation of saga storage

    Stores all saga state in memory using dictionaries.
    Provides fast access but no persistence across restarts.
    """

    def __init__(self):
        self._sagas: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def save_saga_state(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save saga state to memory"""

        async with self._lock:
            self._sagas[saga_id] = {
                "saga_id": saga_id,
                "saga_name": saga_name,
                "status": status.value,
                "steps": steps,
                "context": context,
                "metadata": metadata or {},
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """Load saga state from memory"""

        async with self._lock:
            saga_data = self._sagas.get(saga_id)
            if saga_data:
                # Return a copy to prevent external modification
                return dict(saga_data)
            return None

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state from memory"""

        async with self._lock:
            if saga_id in self._sagas:
                del self._sagas[saga_id]
                return True
            return False

    async def list_sagas(
        self,
        status: SagaStatus | None = None,
        saga_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List sagas with filtering"""
        async with self._lock:
            results = [
                self._create_saga_summary(saga_data)
                for saga_data in self._sagas.values()
                if self._matches_filters(saga_data, status, saga_name)
            ]
            results.sort(key=lambda x: x["updated_at"], reverse=True)
            return results[offset : offset + limit]

    def _matches_filters(
        self, saga_data: dict, status: SagaStatus | None, saga_name: str | None
    ) -> bool:
        """Check if saga matches the given filters."""
        if status and saga_data["status"] != status.value:
            return False
        return not (saga_name and saga_name.lower() not in saga_data["saga_name"].lower())

    def _create_saga_summary(self, saga_data: dict) -> dict[str, Any]:
        """Create a summary dict for a saga."""
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
        async with self._lock:
            saga_data = self._sagas.get(saga_id)
            if not saga_data:
                msg = f"Saga {saga_id} not found"
                raise SagaStorageError(msg)

            step = self._find_step(saga_data, step_name)
            if step is None:
                msg = f"Step {step_name} not found in saga {saga_id}"
                raise SagaStorageError(msg)

            self._apply_step_update(step, status, result, error, executed_at)
            saga_data["updated_at"] = datetime.now(UTC).isoformat()

    def _find_step(self, saga_data: dict[str, Any], step_name: str) -> dict[str, Any] | None:
        """Find a step by name in saga data."""
        for step in saga_data["steps"]:
            if step["name"] == step_name:
                return step  # type: ignore[no-any-return]
        return None

    def _apply_step_update(
        self,
        step: dict,
        status: SagaStepStatus,
        result: Any,
        error: str | None,
        executed_at: datetime | None,
    ) -> None:
        """Apply updates to a step."""
        step["status"] = status.value
        step["result"] = result
        step["error"] = error
        if executed_at:
            step["executed_at"] = executed_at.isoformat()

    async def get_saga_statistics(self) -> dict[str, Any]:
        """Get storage statistics"""

        async with self._lock:
            by_status: dict[str, int] = {}
            for saga_data in self._sagas.values():
                status = saga_data["status"]
                by_status[status] = by_status.get(status, 0) + 1

            return {
                "total_sagas": len(self._sagas),
                "by_status": by_status,
                "memory_usage_bytes": self._estimate_memory_usage(),
            }

    async def cleanup_completed_sagas(
        self, older_than: datetime, statuses: list[SagaStatus] | None = None
    ) -> int:
        """Clean up old completed sagas"""
        statuses = statuses or [SagaStatus.COMPLETED, SagaStatus.ROLLED_BACK]
        status_values = [s.value for s in statuses]

        async with self._lock:
            to_delete = self._find_sagas_to_cleanup(status_values, older_than)
            self._delete_sagas(to_delete)
            return len(to_delete)

    def _find_sagas_to_cleanup(self, status_values: list[str], older_than: datetime) -> list[str]:
        """Find saga IDs that should be cleaned up."""
        return [
            saga_id
            for saga_id, saga_data in self._sagas.items()
            if self._should_cleanup(saga_data, status_values, older_than)
        ]

    def _delete_sagas(self, saga_ids: list[str]) -> None:
        """Delete sagas by their IDs."""
        for saga_id in saga_ids:
            del self._sagas[saga_id]

    def _should_cleanup(
        self, saga_data: dict, status_values: list[str], older_than: datetime
    ) -> bool:
        """Check if a saga should be cleaned up."""
        if saga_data["status"] not in status_values:
            return False
        return self._is_older_than(saga_data, older_than)

    def _is_older_than(self, saga_data: dict, older_than: datetime) -> bool:
        """Check if saga is older than the given datetime."""
        try:
            updated_at = datetime.fromisoformat(saga_data["updated_at"])
            return updated_at < older_than
        except (ValueError, KeyError):
            return False

    async def health_check(self) -> dict[str, Any]:
        """Check storage health"""

        async with self._lock:
            return {
                "status": "healthy",
                "storage_type": "in_memory",
                "total_sagas": len(self._sagas),
                "memory_usage_bytes": self._estimate_memory_usage(),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def _estimate_memory_usage(self) -> int:
        """
        Rough estimate of memory usage

        This is a very approximate calculation for monitoring purposes.
        """
        import sys

        total_size = 0
        for saga_data in self._sagas.values():
            total_size += sys.getsizeof(saga_data)
            total_size += sum(sys.getsizeof(v) for v in saga_data.values())

        return total_size

    async def clear_all(self) -> int:
        """
        Clear all saga data (for testing purposes)

        Returns:
            Number of sagas deleted
        """
        async with self._lock:
            count = len(self._sagas)
            self._sagas.clear()
            return count

    def get_saga_count(self) -> int:
        """Get current saga count (synchronous for testing)"""
        return len(self._sagas)

    async def count(self) -> int:
        """Count total sagas."""
        return len(self._sagas)

    async def export_all(self):
        """Export all records for transfer."""
        async with self._lock:
            # Sort by ID to ensure consistent order
            sorted_sagas = sorted(self._sagas.values(), key=lambda x: x["saga_id"])
            for saga_data in sorted_sagas:
                # Yield a copy
                yield dict(saga_data)

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
