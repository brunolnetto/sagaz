"""Tenant isolation of SQLiteSagaStorage (ADR-020)."""

import pytest

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import system_scope, tenant_scope
from tests.unit.core.storage.backends import _saga_tenancy_scenarios as scenarios

aiosqlite = pytest.importorskip("aiosqlite")

from sagaz.core.storage.backends.sqlite import SQLiteSagaStorage  # noqa: E402


@pytest.fixture
async def storage(tmp_path):
    async with SQLiteSagaStorage(str(tmp_path / "sagas.db")) as s:
        yield s


@pytest.fixture
async def target(tmp_path):
    async with SQLiteSagaStorage(str(tmp_path / "target.db")) as s:
        yield s


class TestSQLiteSagaTenancy:
    @pytest.mark.asyncio
    async def test_isolation_with_same_saga_id(self, storage):
        await scenarios.isolation_with_same_saga_id(storage)

    @pytest.mark.asyncio
    async def test_default_tenant_compatibility(self, storage):
        await scenarios.default_tenant_compatibility(storage)

    @pytest.mark.asyncio
    async def test_system_scope_spans_tenants(self, storage):
        await scenarios.system_scope_spans_tenants(storage)

    @pytest.mark.asyncio
    async def test_scoped_cleanup(self, storage):
        await scenarios.scoped_cleanup(storage)

    @pytest.mark.asyncio
    async def test_import_preserves_tenant(self, storage, target):
        await scenarios.import_preserves_tenant(storage, target)

    @pytest.mark.asyncio
    async def test_transfer_in_system_scope(self, storage):
        await scenarios.transfer_in_system_scope(storage, InMemorySagaStorage())

    @pytest.mark.asyncio
    async def test_statistics_are_scoped(self, storage):
        await scenarios.save(storage)
        with tenant_scope("acme"):
            await scenarios.save(storage)
            assert (await storage.get_saga_statistics())["total"] == 1
        with system_scope():
            assert (await storage.get_saga_statistics())["total"] == 2

    @pytest.mark.asyncio
    async def test_data_survives_reopen_per_tenant(self, tmp_path):
        path = str(tmp_path / "reopen.db")
        async with SQLiteSagaStorage(path) as s:
            with tenant_scope("acme"):
                await scenarios.save(s, "AcmeSaga")
            await scenarios.save(s, "DefaultSaga")
        async with SQLiteSagaStorage(path) as s:
            assert (await s.load_saga_state(scenarios.SAGA_ID))["saga_name"] == "DefaultSaga"
            with tenant_scope("acme"):
                assert (await s.load_saga_state(scenarios.SAGA_ID))["saga_name"] == "AcmeSaga"

    @pytest.mark.asyncio
    async def test_pre_tenant_database_is_migrated_to_default(self, tmp_path):
        path = str(tmp_path / "legacy.db")
        conn = await aiosqlite.connect(path)
        await conn.executescript(
            """
            CREATE TABLE sagas (
                saga_id TEXT PRIMARY KEY,
                saga_name TEXT NOT NULL,
                status TEXT NOT NULL,
                steps TEXT NOT NULL,
                context TEXT NOT NULL,
                metadata TEXT,
                configuration TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO sagas VALUES (
                'order-1', 'LegacySaga', 'completed', '[{"name": "s1", "status": "pending"}]',
                '{"a": 1}', NULL, '["completed"]', '2024-01-01T00:00:00', '2024-01-01T00:00:00'
            );
            """
        )
        await conn.commit()
        await conn.close()

        async with SQLiteSagaStorage(path) as s:
            legacy = await s.load_saga_state("order-1")
            assert legacy["saga_name"] == "LegacySaga"
            assert legacy["tenant_id"] == "default"
            assert legacy["context"] == {"a": 1}
            with tenant_scope("acme"):
                assert await s.load_saga_state("order-1") is None
                await scenarios.save(s, "AcmeSaga")
            # Upgrading is idempotent.
            await s._init_schema()
            assert (await s.load_saga_state("order-1"))["saga_name"] == "LegacySaga"
            with system_scope():
                assert await s.count() == 2

    @pytest.mark.asyncio
    async def test_failed_upgrade_is_rolled_back(self, tmp_path):
        from unittest.mock import AsyncMock

        from sagaz.core.storage.backends.sqlite import _saga_schema

        conn = AsyncMock()
        conn.executescript.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            await _saga_schema._add_tenant_key(conn)
        conn.rollback.assert_awaited_once()
