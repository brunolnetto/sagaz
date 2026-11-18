"""SagaStorageMigrator across tenants (ADR-020).

Migrations are infrastructure: run inside ``system_scope()`` they copy every
tenant's sagas, keeping each record's tenant. Outside it they keep their
historical behaviour, which is now "the default tenant's data".
"""

from types import SimpleNamespace

import pytest

from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import system_scope, tenant_scope
from sagaz.core.types import SagaStatus
from sagaz.storage.migration import SagaStorageMigrator

aiosqlite = pytest.importorskip("aiosqlite")

from sagaz.core.storage.backends.sqlite import SQLiteSagaStorage  # noqa: E402


async def _save(storage, name):
    await storage.save_saga_state(
        "order-1",
        name,
        SagaStatus.COMPLETED,
        [{"name": "s1", "status": "completed"}],
        {"name": name},
        metadata={"source": name},
    )


async def _source() -> SimpleNamespace:
    saga = InMemorySagaStorage()
    await _save(saga, "DefaultSaga")
    for tenant in ("acme", "globex"):
        with tenant_scope(tenant):
            await _save(saga, f"{tenant}-saga")
    return SimpleNamespace(saga=saga, outbox=InMemoryOutboxStorage())


@pytest.mark.asyncio
async def test_migration_in_system_scope_copies_every_tenant(tmp_path):
    source = await _source()
    async with SQLiteSagaStorage(str(tmp_path / "dest.db")) as dest_saga:
        destination = SimpleNamespace(saga=dest_saga, outbox=InMemoryOutboxStorage())
        migrator = SagaStorageMigrator(source, destination)
        with system_scope():
            result = await migrator.migrate(batch_size=2)
            assert result.sagas_transferred == 3
            verification = await migrator.verify()
            assert verification.dest_sagas == 3
            assert verification.ok, verification.to_dict()

        assert (await dest_saga.load_saga_state("order-1"))["saga_name"] == "DefaultSaga"
        for tenant in ("acme", "globex"):
            with tenant_scope(tenant):
                loaded = await dest_saga.load_saga_state("order-1")
                assert loaded["saga_name"] == f"{tenant}-saga"
                assert loaded["tenant_id"] == tenant


@pytest.mark.asyncio
async def test_unscoped_migration_copies_the_default_tenant(tmp_path):
    source = await _source()
    async with SQLiteSagaStorage(str(tmp_path / "dest.db")) as dest_saga:
        destination = SimpleNamespace(saga=dest_saga, outbox=InMemoryOutboxStorage())
        result = await SagaStorageMigrator(source, destination).migrate()
        assert result.sagas_transferred == 1
        with system_scope():
            assert await dest_saga.count() == 1
