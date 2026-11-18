"""Tenant isolation of RedisSagaStorage against a real Redis (ADR-020)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import system_scope, tenant_scope
from sagaz.core.types import SagaStepStatus
from tests.unit.core.storage.backends import _saga_tenancy_scenarios as scenarios

pytestmark = pytest.mark.integration

pytest.importorskip("redis")


@pytest.fixture
def prefix():
    return f"tenancy-{uuid4().hex[:8]}:"


@pytest.fixture
async def storage(redis_url, prefix):
    from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

    async with RedisSagaStorage(redis_url, key_prefix=prefix) as s:
        yield s


@pytest.fixture
async def target(redis_url):
    from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

    async with RedisSagaStorage(redis_url, key_prefix=f"target-{uuid4().hex[:8]}:") as s:
        yield s


@pytest.mark.asyncio
class TestRedisSagaTenancy:
    async def test_isolation_with_same_saga_id(self, storage):
        await scenarios.isolation_with_same_saga_id(storage)

    async def test_default_tenant_compatibility(self, storage):
        await scenarios.default_tenant_compatibility(storage)

    async def test_system_scope_spans_tenants(self, storage):
        await scenarios.system_scope_spans_tenants(storage)

    async def test_scoped_cleanup(self, storage):
        await scenarios.scoped_cleanup(storage)

    async def test_reserved_records_survive_cleanup(self, storage):
        await scenarios.reserved_records_survive_cleanup(storage)

    async def test_import_preserves_tenant(self, storage, target):
        await scenarios.import_preserves_tenant(storage, target)

    async def test_transfer_in_system_scope(self, storage):
        await scenarios.transfer_in_system_scope(storage, InMemorySagaStorage())

    async def test_transfer_from_memory_into_redis(self, target):
        await scenarios.transfer_in_system_scope(InMemorySagaStorage(), target)

    async def test_key_layout(self, storage, prefix):
        """Default-tenant keys are unchanged; other tenants are namespaced."""
        await scenarios.save(storage)
        with tenant_scope("acme"):
            await scenarios.save(storage)
        client = await storage._get_redis()
        assert await client.exists(f"{prefix}{scenarios.SAGA_ID}")
        assert await client.exists(f"sagaz:acme:{prefix}{scenarios.SAGA_ID}")
        assert await client.sismember(f"sagaz:acme:{prefix}index:status:completed", "order-1")

    async def test_legacy_default_records_get_their_tenant(self, storage, prefix):
        """Records written before tenancy (no tenant_id field) read as 'default'."""
        import json

        client = await storage._get_redis()
        legacy = {
            "saga_id": "legacy",
            "saga_name": "Legacy",
            "status": "completed",
            "steps": [],
            "context": {},
            "metadata": {},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        await client.hset(f"{prefix}legacy", mapping={"data": json.dumps(legacy)})
        await client.sadd(f"{prefix}index:status:completed", "legacy")
        assert (await storage.load_saga_state("legacy"))["tenant_id"] == "default"
        with system_scope():
            exported = [r async for r in storage.export_all()]
            assert [(r["saga_id"], r["tenant_id"]) for r in exported] == [("legacy", "default")]

    async def test_system_scope_statistics_and_step_updates(self, storage):
        await scenarios.save(storage)
        with tenant_scope("acme"):
            await scenarios.save(storage)
        with tenant_scope("acme"):
            assert (await storage.get_saga_statistics())["total_sagas"] == 1
        with system_scope():
            stats = await storage.get_saga_statistics()
            assert stats["total_sagas"] == 2
            assert stats["by_status"]["completed"] == 2
            await storage.update_step_state(scenarios.SAGA_ID, "s1", SagaStepStatus.FAILED)
            with pytest.raises(Exception, match="not found"):
                await storage.update_step_state("missing", "s1", SagaStepStatus.FAILED)
            assert await storage.delete_saga_state(scenarios.SAGA_ID) is True
            assert await storage.count() == 0

    async def test_default_keys_ignore_tenants_sharing_the_prefix(self, redis_url):
        """With key_prefix 'sagaz:', other tenants' keys also match 'sagaz:*'."""
        from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

        async with RedisSagaStorage(redis_url, key_prefix="sagaz:") as s:
            client = await s._get_redis()
            await client.flushdb()
            with tenant_scope("acme"):
                await scenarios.save(s, "AcmeSaga")
            assert await s.list_sagas() == []
            assert [r async for r in s.export_all()] == []
            await client.flushdb()
