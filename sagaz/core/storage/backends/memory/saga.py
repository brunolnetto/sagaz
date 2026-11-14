"""
In-memory storage implementation for saga state

Provides a simple in-memory storage backend for development and testing.
Not suitable for production use as state is lost on process restart.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sagaz.core.storage._tenancy import TENANT_FIELD, scoped_tenant, write_tenant
from sagaz.core.storage._tenant_records import record_tenant_scope
from sagaz.core.storage.base import SagaStorage, SagaStorageError
from sagaz.core.tenant import DEFAULT_TENANT
from sagaz.core.types import SagaStatus, SagaStepStatus

_Partition = dict[str, dict[str, Any]]


class InMemorySagaStorage(SagaStorage):
    """
    In-memory implementation of saga storage

    Stores all saga state in memory using dictionaries.
    Provides fast access but no persistence across restarts.

    Sagas are partitioned by tenant (ADR-020): one ``{saga_id: record}`` dict
    per tenant, so two tenants may use the same saga id. Every operation sees
    only the current tenant's partition, except in the system scope, which
    sees all of them (there, operations by saga id act on every tenant's saga
    with that id, and ``load_saga_state`` returns the first one found).
    """

    def __init__(self):
        """Initialise an empty in-memory saga store with an async lock."""
        self._partitions: dict[str, _Partition] = {}
        self._lock = asyncio.Lock()

    @property
    def _sagas(self) -> _Partition:
        """The default tenant's partition (where unscoped code reads and writes)."""
        return self._partitions.setdefault(DEFAULT_TENANT, {})

    def _visible_partitions(self) -> list[tuple[str, _Partition]]:
        """``(tenant_id, partition)`` pairs visible in the current scope."""
        tenant = scoped_tenant()
        if tenant is None:
            return list(self._partitions.items())
        return [(tenant, self._partitions.get(tenant, {}))]

    def _visible(self) -> Iterator[dict[str, Any]]:
        """Every saga record visible in the current scope."""
        for _, partition in self._visible_partitions():
            yield from partition.values()

    def _matching(self, saga_id: str) -> list[dict[str, Any]]:
        """Visible records with ``saga_id`` (one per tenant in the system scope)."""
        return [
            partition[saga_id]
            for _, partition in self._visible_partitions()
            if saga_id in partition
        ]

    def _visible_count(self) -> int:
        """Number of sagas visible in the current scope."""
        return sum(len(partition) for _, partition in self._visible_partitions())

    async def save_saga_state(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        configuration: list[str] | None = None,
    ) -> None:
        """Save saga state to memory"""

        tenant_id = write_tenant()
        async with self._lock:
            self._partitions.setdefault(tenant_id, {})[saga_id] = {
                TENANT_FIELD: tenant_id,
                "saga_id": saga_id,
                "saga_name": saga_name,
                "status": status.value,
                "steps": steps,
                "context": context,
                "metadata": metadata or {},
                "configuration": list(configuration) if configuration else [status.value],
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        """Load saga state from memory"""

        async with self._lock:
            matches = self._matching(saga_id)
            if matches:
                # Return a copy to prevent external modification.
                result = dict(matches[0])
                result["configuration"] = list(result.get("configuration") or [result["status"]])
                return result
            return None

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state from memory"""

        async with self._lock:
            deleted = False
            for _, partition in self._visible_partitions():
                deleted = partition.pop(saga_id, None) is not None or deleted
            return deleted

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
                for saga_data in self._visible()
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
            TENANT_FIELD: saga_data.get(TENANT_FIELD, DEFAULT_TENANT),
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
            matches = self._matching(saga_id)
            if not matches:
                msg = f"Saga {saga_id} not found"
                raise SagaStorageError(msg)

            for saga_data in matches:
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
            for saga_data in self._visible():
                status = saga_data["status"]
                by_status[status] = by_status.get(status, 0) + 1

            return {
                "total_sagas": self._visible_count(),
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
            deleted = 0
            for _, partition in self._visible_partitions():
                to_delete = self._find_sagas_to_cleanup(partition, status_values, older_than)
                for saga_id in to_delete:
                    del partition[saga_id]
                deleted += len(to_delete)
            return deleted

    def _find_sagas_to_cleanup(
        self, partition: _Partition, status_values: list[str], older_than: datetime
    ) -> list[str]:
        """Find saga IDs in ``partition`` that should be cleaned up."""
        return [
            saga_id
            for saga_id, saga_data in partition.items()
            if self._should_cleanup(saga_data, status_values, older_than)
        ]

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
                "total_sagas": self._visible_count(),
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
        for saga_data in self._visible():
            total_size += sys.getsizeof(saga_data)
            total_size += sum(sys.getsizeof(v) for v in saga_data.values())

        return total_size

    async def clear_all(self) -> int:
        """
        Clear the saga data of the current scope (for testing purposes)

        Returns:
            Number of sagas deleted
        """
        async with self._lock:
            count = self._visible_count()
            for _, partition in self._visible_partitions():
                partition.clear()
            return count

    def get_saga_count(self) -> int:
        """Get current saga count (synchronous for testing)"""
        return self._visible_count()

    async def count(self) -> int:
        """Count total sagas."""
        return self._visible_count()

    async def export_all(self):
        """Export all records of the current scope, each with its ``tenant_id``."""
        async with self._lock:
            records = [
                {**saga_data, TENANT_FIELD: tenant_id}
                for tenant_id, partition in self._visible_partitions()
                for saga_data in partition.values()
            ]
            # Sort by ID (then tenant) to ensure consistent order
            records.sort(key=lambda x: (x["saga_id"], x[TENANT_FIELD]))
            for record in records:
                # Fallback for legacy in-memory records.
                record["configuration"] = list(record.get("configuration") or [record["status"]])
                yield record

    async def import_record(self, record: dict[str, Any]) -> None:
        """Import a single record from transfer, into the record's own tenant."""
        with record_tenant_scope(record):
            await self.save_saga_state(
                saga_id=record["saga_id"],
                saga_name=record["saga_name"],
                status=SagaStatus(record["status"]),
                steps=record.get("steps", []),
                context=record.get("context", {}),
                metadata=record.get("metadata"),
                configuration=record.get("configuration") or [record["status"]],
            )
