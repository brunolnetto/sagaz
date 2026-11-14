"""Tenant isolation of RedisSagaStorage on an in-process fake Redis (ADR-020).

The same scenarios run against a real Redis in
tests/integration/test_saga_tenancy_redis.py; this fake implements just the
commands the saga storage uses, so the logic is also covered by unit runs.
"""

from __future__ import annotations

import fnmatch
from typing import Any

import pytest

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import system_scope, tenant_scope
from sagaz.core.types import SagaStepStatus
from tests.unit.core.storage.backends import _saga_tenancy_scenarios as scenarios

pytest.importorskip("redis")


def _b(value: Any) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode()


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[bytes, Any] = {}

    async def ping(self) -> bool:
        return True

    async def hset(self, key, mapping):
        self.data.setdefault(_b(key), {}).update({_b(k): _b(v) for k, v in mapping.items()})

    async def hget(self, key, field):
        return self.data.get(_b(key), {}).get(_b(field))

    async def sadd(self, key, member):
        self.data.setdefault(_b(key), set()).add(_b(member))

    async def srem(self, key, member):
        members = self.data.get(_b(key), set())
        members.discard(_b(member))
        if not members:
            self.data.pop(_b(key), None)

    async def smembers(self, key):
        return set(self.data.get(_b(key), set()))

    async def scard(self, key):
        return len(self.data.get(_b(key), set()))

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        return 1 if self.data.pop(_b(key), None) is not None else 0

    async def keys(self, pattern):
        return [k for k in self.data if fnmatch.fnmatchcase(k.decode(), pattern)]

    async def scan_iter(self, match, count=None):
        for key in await self.keys(match):
            yield key

    async def info(self, section=None):
        return {"used_memory": 1, "used_memory_human": "1B"}

    async def close(self):
        return None

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.calls: list[tuple[str, tuple]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def __getattr__(self, name):
        async def queue(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return queue

    async def execute(self):
        return [await getattr(self.redis, n)(*a, **kw) for n, a, kw in self.calls]


def _storage(prefix: str = "saga:"):
    from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

    storage = RedisSagaStorage("redis://fake", key_prefix=prefix)
    storage._redis = FakeRedis()
    return storage


@pytest.fixture
def storage():
    return _storage()


@pytest.mark.asyncio
class TestRedisSagaTenancyUnit:
    async def test_isolation_with_same_saga_id(self, storage):
        await scenarios.isolation_with_same_saga_id(storage)

    async def test_default_tenant_compatibility(self, storage):
        await scenarios.default_tenant_compatibility(storage)

    async def test_system_scope_spans_tenants(self, storage):
        await scenarios.system_scope_spans_tenants(storage)

    async def test_scoped_cleanup(self, storage):
        await scenarios.scoped_cleanup(storage)

    async def test_import_preserves_tenant(self, storage):
        await scenarios.import_preserves_tenant(storage, _storage("target:"))

    async def test_transfer_in_system_scope(self, storage):
        await scenarios.transfer_in_system_scope(storage, InMemorySagaStorage())

    async def test_key_layout(self, storage):
        await scenarios.save(storage)
        with tenant_scope("acme"):
            await scenarios.save(storage)
        keys = set(storage._redis.data)
        assert b"saga:order-1" in keys
        assert b"sagaz:acme:saga:order-1" in keys
        assert b"sagaz:acme:saga:index:status:completed" in keys

    async def test_system_scope_statistics_step_updates_and_deletes(self, storage):
        await scenarios.save(storage)
        with tenant_scope("acme"):
            await scenarios.save(storage)
        with system_scope():
            stats = await storage.get_saga_statistics()
            assert stats["total_sagas"] == 2
            assert stats["by_status"]["completed"] == 2
            await storage.update_step_state(scenarios.SAGA_ID, "s1", SagaStepStatus.FAILED)
            with pytest.raises(Exception, match="not found"):
                await storage.update_step_state("missing", "s1", SagaStepStatus.FAILED)
            assert await storage.delete_saga_state(scenarios.SAGA_ID) is True
            assert await storage.delete_saga_state(scenarios.SAGA_ID) is False
            assert await storage.load_saga_state(scenarios.SAGA_ID) is None

    async def test_default_keys_ignore_tenants_sharing_the_prefix(self):
        storage = _storage("sagaz:")
        with tenant_scope("acme"):
            await scenarios.save(storage, "AcmeSaga")
        assert await storage.list_sagas() == []
        assert [r async for r in storage.export_all()] == []
        with system_scope():
            assert [s["tenant_id"] for s in await storage.list_sagas()] == ["acme"]
