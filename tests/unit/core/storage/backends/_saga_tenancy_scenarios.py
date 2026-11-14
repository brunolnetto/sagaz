"""Tenant-isolation scenarios shared by the saga storage backend tests (ADR-020).

Each scenario takes empty storages and asserts the ADR-020 contract: a saga id
of tenant A is invisible to tenant B (and both may use the same id), unscoped
code keeps working as the default tenant, the system scope spans every tenant,
and transfers keep each record's tenant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sagaz.core.storage.transfer import TransferConfig, TransferService
from sagaz.core.tenant import CrossTenantAccessError, system_scope, tenant_scope
from sagaz.core.types import SagaStatus, SagaStepStatus

SAGA_ID = "order-1"


async def save(
    storage: Any, name: str = "OrderSaga", status: SagaStatus = SagaStatus.COMPLETED
) -> None:
    await storage.save_saga_state(
        SAGA_ID, name, status, [{"name": "s1", "status": "pending"}], {"name": name}
    )


async def _absent_for_other_tenant(storage: Any) -> None:
    assert await storage.load_saga_state(SAGA_ID) is None
    assert await storage.list_sagas() == []
    assert await storage.count() == 0
    assert await storage.delete_saga_state(SAGA_ID) is False
    await _update_step_not_found(storage)


async def _update_step_not_found(storage: Any) -> None:
    """Updating an invisible saga either raises or changes nothing."""
    try:
        await storage.update_step_state(SAGA_ID, "s1", SagaStepStatus.FAILED)
    except Exception as exc:  # backends differ: SagaStorageError / SagaNotFoundError
        assert "not found" in str(exc).lower()
    assert await storage.load_saga_state(SAGA_ID) is None


async def isolation_with_same_saga_id(storage: Any) -> None:
    with tenant_scope("acme"):
        await save(storage, "AcmeSaga")
    with tenant_scope("globex"):
        await _absent_for_other_tenant(storage)
        await save(storage, "GlobexSaga")
        assert (await storage.load_saga_state(SAGA_ID))["saga_name"] == "GlobexSaga"
        assert [s["saga_id"] for s in await storage.list_sagas()] == [SAGA_ID]
        assert await storage.count() == 1
    with tenant_scope("acme"):
        loaded = await storage.load_saga_state(SAGA_ID)
        assert loaded["saga_name"] == "AcmeSaga"
        assert loaded["tenant_id"] == "acme"
        await storage.update_step_state(SAGA_ID, "s1", SagaStepStatus.COMPLETED)
        updated = await storage.load_saga_state(SAGA_ID)
        assert updated["steps"][0]["status"] == "completed"
        assert await storage.delete_saga_state(SAGA_ID) is True
        assert await storage.load_saga_state(SAGA_ID) is None
    with tenant_scope("globex"):
        survivor = await storage.load_saga_state(SAGA_ID)
        assert survivor["saga_name"] == "GlobexSaga"
        assert survivor["steps"][0]["status"] == "pending"


async def default_tenant_compatibility(storage: Any) -> None:
    await save(storage)
    loaded = await storage.load_saga_state(SAGA_ID)
    assert loaded["saga_name"] == "OrderSaga"
    assert loaded.get("tenant_id", "default") == "default"
    assert [s["saga_id"] for s in await storage.list_sagas()] == [SAGA_ID]
    with tenant_scope("default"):
        assert await storage.load_saga_state(SAGA_ID) is not None
    with tenant_scope("acme"):
        await _absent_for_other_tenant(storage)
    assert await storage.count() == 1


async def system_scope_spans_tenants(storage: Any) -> None:
    await save(storage, "DefaultSaga")
    with tenant_scope("acme"):
        await save(storage, "AcmeSaga")
    with tenant_scope("globex"):
        await save(storage, "GlobexSaga", SagaStatus.EXECUTING)
    with system_scope():
        listed = await storage.list_sagas()
        assert sorted(s["saga_name"] for s in listed) == ["AcmeSaga", "DefaultSaga", "GlobexSaga"]
        assert await storage.count() == 3
        exported = [record async for record in storage.export_all()]
        assert sorted((r["tenant_id"], r["saga_name"]) for r in exported) == [
            ("acme", "AcmeSaga"),
            ("default", "DefaultSaga"),
            ("globex", "GlobexSaga"),
        ]
        loaded = await storage.load_saga_state(SAGA_ID)
        assert loaded["tenant_id"] in {"acme", "default", "globex"}
        future = datetime.now(UTC) + timedelta(hours=1)
        assert await storage.cleanup_completed_sagas(older_than=future) == 2
        assert await storage.count() == 1
    with tenant_scope("globex"):
        assert await storage.count() == 1


async def scoped_cleanup(storage: Any) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    await save(storage)
    with tenant_scope("acme"):
        await save(storage)
        assert await storage.cleanup_completed_sagas(older_than=future) == 1
        assert await storage.count() == 0
    assert await storage.count() == 1


async def import_preserves_tenant(source: Any, target: Any) -> None:
    await save(source, "DefaultSaga")
    with tenant_scope("acme"):
        await save(source, "AcmeSaga")
    with system_scope():
        async for record in source.export_all():
            await target.import_record(record)
        assert await target.count() == 2
    assert (await target.load_saga_state(SAGA_ID))["saga_name"] == "DefaultSaga"
    with tenant_scope("acme"):
        loaded = await target.load_saga_state(SAGA_ID)
        assert loaded["saga_name"] == "AcmeSaga"
        assert loaded["tenant_id"] == "acme"
    record = {"saga_id": "x", "saga_name": "X", "status": "completed", "tenant_id": "acme"}
    with tenant_scope("globex"), pytest.raises(CrossTenantAccessError):
        await target.import_record(record)


async def transfer_in_system_scope(source: Any, target: Any) -> None:
    """``TransferService`` run in the system scope copies every tenant's sagas."""
    await save(source, "DefaultSaga")
    with tenant_scope("acme"):
        await save(source, "AcmeSaga")
    with system_scope():
        result = await TransferService(source, target, TransferConfig(batch_size=1)).transfer_all()
        assert result.transferred == 2
    assert (await target.load_saga_state(SAGA_ID))["saga_name"] == "DefaultSaga"
    with tenant_scope("acme"):
        assert (await target.load_saga_state(SAGA_ID))["saga_name"] == "AcmeSaga"


async def reserved_records_survive_cleanup(storage: Any) -> None:
    """Cleanup never deletes sagaz's own records (tenant registry, ``__sagaz_*``)."""
    from sagaz.core.tenant import TenantContext, TenantRegistry

    registry = TenantRegistry(storage)
    registry.register(TenantContext("acme", plan="premium"))
    await registry.save()
    await save(storage)  # an ordinary completed saga, which cleanup should remove

    every_status = list(SagaStatus)
    future = datetime.now(UTC) + timedelta(days=1)
    with system_scope():
        deleted = await storage.cleanup_completed_sagas(future, every_status)
    assert deleted == 1
    assert await storage.cleanup_completed_sagas(future) == 0

    reloaded = await TenantRegistry.from_storage(storage)
    assert reloaded.get("acme").plan == "premium"
