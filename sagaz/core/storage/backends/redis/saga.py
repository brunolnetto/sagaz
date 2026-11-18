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
from sagaz.core.storage._tenancy import TENANT_FIELD, write_tenant
from sagaz.core.storage._tenant_records import record_tenant_scope
from sagaz.core.storage.backends.redis._saga_maintenance import _RedisSagaMaintenanceMixin
from sagaz.core.storage.backends.redis._saga_query import _RedisSagaQueryMixin
from sagaz.core.storage.base import (
    SagaNotFoundError,
    SagaStorage,
    SagaStorageConnectionError,
    SagaStorageError,
)
from sagaz.core.tenant import is_system_scope, tenant_scope
from sagaz.core.types import SagaStatus, SagaStepStatus

try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis: Any = None  # type: ignore[assignment, no-redef]


class RedisSagaStorage(_RedisSagaQueryMixin, _RedisSagaMaintenanceMixin, SagaStorage):
    """
    Redis implementation of saga storage

    Uses Redis for persistent, distributed saga state storage.
    Supports automatic cleanup and clustering.

    Tenant isolation (ADR-020): each tenant has its own keyspace (see
    :mod:`._saga_tenancy`), so tenants may share saga ids. In the system scope,
    operations run against every tenant; by saga id they act on every tenant's
    saga with that id, and ``load_saga_state`` returns the first one found.

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
        """
        Configure the Redis saga storage backend.

        Args:
            redis_url: Redis connection URL (supports ``redis://``, ``rediss://``,
                and ``unix://`` schemes).
            key_prefix: Namespace prefix prepended to every Redis key.
            default_ttl: Optional TTL (seconds) applied to completed/rolled-back
                saga records; ``None`` means keys never expire.
            **redis_kwargs: Extra keyword arguments forwarded to the Redis client.

        Raises:
            MissingDependencyError: If *redis* (``redis[asyncio]``) is not installed.
        """
        if not REDIS_AVAILABLE:
            msg = "redis"
            raise MissingDependencyError(msg, "Redis storage backend")

        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.default_ttl = default_ttl
        self.redis_kwargs = redis_kwargs
        self._redis: Any = None
        self._lock = asyncio.Lock()

    async def _get_redis(self):
        """Get Redis connection, creating if necessary"""
        if self._redis is None:
            try:
                self._redis = redis.from_url(self.redis_url, **self.redis_kwargs)
                # Test connection
                await self._redis.ping()  # type: ignore[attr-defined]
            except Exception as e:
                msg = f"Failed to connect to Redis: {e}"
                raise SagaStorageConnectionError(msg) from e

        return self._redis

    def _saga_key(self, saga_id: str) -> str:
        """Generate Redis key for saga (in the current tenant's keyspace)"""
        return f"{self._tenant_prefix()}{saga_id}"

    def _step_key(self, saga_id: str, step_name: str) -> str:
        """Generate Redis key for step"""
        return f"{self._tenant_prefix()}{saga_id}:step:{step_name}"

    def _index_key(self, index_type: str) -> str:
        """Generate Redis key for indexes"""
        return f"{self._tenant_prefix()}index:{index_type}"

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
        """Save saga state to Redis"""

        redis_client = await self._get_redis()

        saga_data = {
            TENANT_FIELD: write_tenant(),
            "saga_id": saga_id,
            "saga_name": saga_name,
            "status": status.value,
            "steps": steps,
            "context": context,
            "metadata": metadata or {},
            "configuration": configuration or [status.value],
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
        if is_system_scope():
            found = await self._for_each_tenant(self.load_saga_state, saga_id)
            return next((data for _, data in found if data), None)

        redis_client = await self._get_redis()
        saga_key = self._saga_key(saga_id)

        saga_data_json = await redis_client.hget(saga_key, "data")
        if not saga_data_json:
            return None

        try:
            saga_data = json.loads(saga_data_json)
            saga_data["configuration"] = saga_data.get("configuration") or [saga_data["status"]]
            return self._with_tenant(saga_data)
        except json.JSONDecodeError as e:
            msg = f"Failed to decode saga data for {saga_id}: {e}"
            raise SagaStorageError(msg) from e

    async def delete_saga_state(self, saga_id: str) -> bool:
        """Delete saga state from Redis"""
        if is_system_scope():
            deleted = await self._for_each_tenant(self.delete_saga_state, saga_id)
            return any(result for _, result in deleted)

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
        if is_system_scope():
            per_tenant = await self._for_each_tenant(
                self.list_sagas, status, saga_name, limit=offset + limit
            )
            merged = [summary for _, summaries in per_tenant for summary in summaries]
            merged.sort(key=lambda x: x["created_at"], reverse=True)
            return merged[offset : offset + limit]

        redis_client = await self._get_redis()
        saga_ids = await self._get_filtered_saga_ids(redis_client, status, saga_name)

        # Apply pagination
        saga_id_list = list(saga_ids)[offset : offset + limit]

        # Load and build summaries
        results = await self._build_saga_summaries(saga_id_list)

        # Sort by created_at (newest first)
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results

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
        if is_system_scope():
            await self._update_step_in_every_tenant(
                saga_id, step_name, status, result, error, executed_at
            )
            return

        saga_data = await self.load_saga_state(saga_id)
        if not saga_data:
            msg = f"Saga {saga_id} not found"
            raise SagaNotFoundError(msg)

        if not self._update_step_in_data(saga_data, step_name, status, result, error, executed_at):
            msg = f"Step {step_name} not found in saga {saga_id}"
            raise SagaStorageError(msg)

        saga_data["updated_at"] = datetime.now(UTC).isoformat()
        await self._save_updated_saga(saga_data)

    async def _update_step_in_every_tenant(self, saga_id: str, *update: Any) -> None:
        """System scope: update the step in every tenant's saga with ``saga_id``."""
        owners = [
            t for t, data in await self._for_each_tenant(self.load_saga_state, saga_id) if data
        ]
        if not owners:
            msg = f"Saga {saga_id} not found"
            raise SagaNotFoundError(msg)
        for tenant in owners:
            with tenant_scope(tenant):
                await self.update_step_state(saga_id, *update)

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

    async def close(self):
        """Close connection explicitly."""
        if self._redis:
            await self._redis.close()

    async def __aenter__(self):
        """Async context manager entry"""
        await self._get_redis()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def export_all(self):
        """Export all records of the current scope, each with its ``tenant_id``."""
        redis_client = await self._get_redis()
        tenants = await self._all_tenants() if is_system_scope() else [write_tenant()]

        # Scopes are entered around each await only, never across a yield, so
        # the consumer of this generator keeps its own scope.
        for tenant in tenants:
            with tenant_scope(tenant):
                saga_ids = await self._get_all_saga_ids(redis_client)
            for saga_id in sorted(saga_ids):
                with tenant_scope(tenant):
                    saga_data = await self.load_saga_state(saga_id)
                if saga_data:
                    yield saga_data

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
