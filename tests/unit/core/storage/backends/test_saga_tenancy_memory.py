"""Tenant isolation of InMemorySagaStorage (ADR-020)."""

from datetime import UTC, datetime, timedelta

import pytest

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.base import SagaStorageError
from sagaz.core.tenant import CrossTenantAccessError, system_scope, tenant_scope
from sagaz.core.types import SagaStatus, SagaStepStatus

STEPS = [{"name": "s1", "status": "pending"}]


async def _save(storage, saga_id="order-1", name="OrderSaga", status=SagaStatus.COMPLETED):
    await storage.save_saga_state(saga_id, name, status, [dict(s) for s in STEPS], {"k": 1})


@pytest.fixture
def storage():
    return InMemorySagaStorage()


class TestMemorySagaTenancy:
    @pytest.mark.asyncio
    async def test_same_saga_id_is_isolated_between_tenants(self, storage):
        with tenant_scope("acme"):
            await _save(storage, name="AcmeSaga")
        with tenant_scope("globex"):
            assert await storage.load_saga_state("order-1") is None
            assert await storage.list_sagas() == []
            assert await storage.delete_saga_state("order-1") is False
            with pytest.raises(SagaStorageError):
                await storage.update_step_state("order-1", "s1", SagaStepStatus.COMPLETED)
            await _save(storage, name="GlobexSaga")
            assert (await storage.load_saga_state("order-1"))["saga_name"] == "GlobexSaga"
            assert await storage.count() == 1
            assert (await storage.get_saga_statistics())["total_sagas"] == 1
        with tenant_scope("acme"):
            loaded = await storage.load_saga_state("order-1")
            assert loaded["saga_name"] == "AcmeSaga"
            assert loaded["tenant_id"] == "acme"
            await storage.update_step_state("order-1", "s1", SagaStepStatus.COMPLETED)
            assert await storage.delete_saga_state("order-1") is True
        with tenant_scope("globex"):
            loaded = await storage.load_saga_state("order-1")
            assert loaded["steps"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_default_tenant_compatibility(self, storage):
        await _save(storage)
        assert (await storage.load_saga_state("order-1"))["tenant_id"] == "default"
        assert [s["saga_id"] for s in await storage.list_sagas()] == ["order-1"]
        with tenant_scope("default"):
            assert await storage.load_saga_state("order-1") is not None
        with tenant_scope("acme"):
            assert await storage.load_saga_state("order-1") is None
        assert "order-1" in storage._sagas

    @pytest.mark.asyncio
    async def test_system_scope_spans_tenants(self, storage):
        await _save(storage)
        with tenant_scope("acme"):
            await _save(storage)
        with system_scope():
            listed = await storage.list_sagas()
            assert sorted(s["tenant_id"] for s in listed) == ["acme", "default"]
            assert await storage.count() == 2
            assert (await storage.health_check())["total_sagas"] == 2
            exported = [r async for r in storage.export_all()]
            assert [(r["saga_id"], r["tenant_id"]) for r in exported] == [
                ("order-1", "acme"),
                ("order-1", "default"),
            ]
            await storage.update_step_state("order-1", "s1", SagaStepStatus.FAILED)
            assert await storage.delete_saga_state("order-1") is True
            assert await storage.count() == 0

    @pytest.mark.asyncio
    async def test_import_preserves_tenant(self, storage):
        source = InMemorySagaStorage()
        with tenant_scope("acme"):
            await _save(source)
        await _save(source)
        target = InMemorySagaStorage()
        with system_scope():
            async for record in source.export_all():
                await target.import_record(record)
            assert await target.count() == 2
        with tenant_scope("acme"):
            assert (await target.load_saga_state("order-1"))["tenant_id"] == "acme"
        assert (await target.load_saga_state("order-1"))["tenant_id"] == "default"

    @pytest.mark.asyncio
    async def test_import_in_tenant_scope_rejects_foreign_record(self, storage):
        record = {"saga_id": "x", "saga_name": "n", "status": "completed", "tenant_id": "acme"}
        with tenant_scope("globex"), pytest.raises(CrossTenantAccessError):
            await storage.import_record(record)
        with tenant_scope("globex"):
            await storage.import_record({**record, "tenant_id": None})
            assert (await storage.load_saga_state("x"))["tenant_id"] == "globex"

    @pytest.mark.asyncio
    async def test_cleanup_and_clear_are_scoped(self, storage):
        future = datetime.now(UTC) + timedelta(hours=1)
        await _save(storage)
        with tenant_scope("acme"):
            await _save(storage)
            assert await storage.cleanup_completed_sagas(older_than=future) == 1
            await _save(storage)
            assert await storage.clear_all() == 1
            assert storage.get_saga_count() == 0
        assert await storage.count() == 1
        with tenant_scope("acme"):
            await _save(storage)
        with system_scope():
            assert await storage.cleanup_completed_sagas(older_than=future) == 2
