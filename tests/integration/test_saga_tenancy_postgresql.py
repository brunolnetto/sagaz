"""Tenant isolation of PostgreSQLSagaStorage against a real PostgreSQL (ADR-020).

Besides the backend's own filtering, these tests prove that row-level security
enforces isolation by itself for an ordinary (non-superuser, no BYPASSRLS) role,
and that a database created before tenancy is upgraded in place.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import system_scope, tenant_scope
from sagaz.core.types import SagaStepStatus
from tests.unit.core.storage.backends import _saga_tenancy_scenarios as scenarios

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

# The saga schema as shipped before tenancy (saga_id primary key, no tenant_id).
PRE_TENANT_SCHEMA = """
    CREATE TABLE sagas (
        saga_id VARCHAR(255) PRIMARY KEY,
        saga_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        context JSONB,
        metadata JSONB,
        configuration JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    CREATE TABLE saga_steps (
        id SERIAL PRIMARY KEY,
        saga_id VARCHAR(255) REFERENCES sagas(saga_id) ON DELETE CASCADE,
        step_name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL,
        result JSONB,
        error TEXT,
        executed_at TIMESTAMP WITH TIME ZONE,
        compensated_at TIMESTAMP WITH TIME ZONE,
        retry_count INTEGER DEFAULT 0,
        duration_ms DOUBLE PRECISION,
        UNIQUE(saga_id, step_name)
    );
    INSERT INTO sagas (saga_id, saga_name, status, context, configuration)
        VALUES ('order-1', 'LegacySaga', 'completed', '{"a": 1}', '["completed"]');
    INSERT INTO saga_steps (saga_id, step_name, status) VALUES ('order-1', 's1', 'completed');
"""


def _storage(url):
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    return PostgreSQLSagaStorage(url, pool_min_size=1, pool_max_size=2)


@pytest.fixture
async def storage(isolated_postgres_url):
    async with _storage(isolated_postgres_url) as s:
        yield s


@pytest.mark.asyncio
class TestPostgreSQLSagaTenancy:
    async def test_isolation_with_same_saga_id(self, storage):
        await scenarios.isolation_with_same_saga_id(storage)

    async def test_default_tenant_compatibility(self, storage):
        await scenarios.default_tenant_compatibility(storage)

    async def test_system_scope_spans_tenants(self, storage):
        await scenarios.system_scope_spans_tenants(storage)

    async def test_scoped_cleanup(self, storage):
        await scenarios.scoped_cleanup(storage)

    async def test_import_preserves_tenant(self, storage):
        await scenarios.import_preserves_tenant(storage, InMemorySagaStorage())

    async def test_import_into_postgresql_preserves_tenant(self, storage):
        await scenarios.import_preserves_tenant(InMemorySagaStorage(), storage)

    async def test_transfer_in_system_scope(self, storage):
        await scenarios.transfer_in_system_scope(storage, InMemorySagaStorage())

    async def test_statistics_and_step_updates_per_tenant(self, storage):
        await scenarios.save(storage)
        with tenant_scope("acme"):
            await scenarios.save(storage)
            assert (await storage.get_saga_statistics())["total_sagas"] == 1
            await storage.update_step_state(scenarios.SAGA_ID, "s1", SagaStepStatus.FAILED)
            listed = await storage.list_sagas()
            assert [(s["tenant_id"], s["step_count"]) for s in listed] == [("acme", 1)]
        assert (await storage.load_saga_state(scenarios.SAGA_ID))["steps"][0]["status"] == (
            "pending"
        )
        with system_scope():
            assert (await storage.get_saga_statistics())["total_sagas"] == 2
            assert (await storage.health_check())["status"] == "healthy"

    async def test_storage_works_as_an_ordinary_role(self, app_role_url):
        """The tables are owned by a non-superuser role, so RLS (FORCE) applies to it."""
        async with _storage(app_role_url) as s:
            await scenarios.isolation_with_same_saga_id(s)
            await scenarios.save(s, "DefaultSaga")
            with system_scope():
                assert await s.count() == 2

    async def test_row_level_security_enforces_isolation(self, app_role_url):
        """Raw SQL as an ordinary role only sees and writes its app.tenant_id's rows."""
        async with _storage(app_role_url) as s:
            with tenant_scope("acme"):
                await scenarios.save(s, "AcmeSaga")
            with tenant_scope("globex"):
                await scenarios.save(s, "GlobexSaga")

        conn = await asyncpg.connect(app_role_url)
        try:
            assert not await conn.fetchval(
                "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"
            )
            await conn.execute("SELECT set_config('app.tenant_id', 'acme', false)")
            rows = await conn.fetch("SELECT tenant_id, saga_name FROM sagas")
            assert [(r["tenant_id"], r["saga_name"]) for r in rows] == [("acme", "AcmeSaga")]
            steps = await conn.fetch("SELECT tenant_id FROM saga_steps")
            assert {r["tenant_id"] for r in steps} == {"acme"}
            # Updates and deletes cannot reach the other tenant's rows either.
            assert await conn.execute("DELETE FROM sagas WHERE tenant_id = 'globex'") == "DELETE 0"
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="row-level"):
                await conn.execute(
                    "INSERT INTO sagas (tenant_id, saga_id, saga_name, status) "
                    "VALUES ('globex', 'intruder', 'X', 'completed')"
                )
            # Without app.tenant_id the session is the default tenant (no rows here).
            await conn.execute("SELECT set_config('app.tenant_id', '', false)")
            assert await conn.fetch("SELECT * FROM sagas") == []
            # The system scope sees every tenant.
            await conn.execute("SELECT set_config('app.tenant_id', '*', false)")
            assert await conn.fetchval("SELECT COUNT(*) FROM sagas") == 2
        finally:
            await conn.close()

    async def test_pre_tenant_database_is_upgraded(self, isolated_postgres_url):
        conn = await asyncpg.connect(isolated_postgres_url)
        try:
            await conn.execute(PRE_TENANT_SCHEMA)
        finally:
            await conn.close()

        async with _storage(isolated_postgres_url) as s:
            legacy = await s.load_saga_state("order-1")
            assert legacy["saga_name"] == "LegacySaga"
            assert legacy["tenant_id"] == "default"
            assert legacy["context"] == {"a": 1}
            assert [step["name"] for step in legacy["steps"]] == ["s1"]
            with tenant_scope("acme"):
                assert await s.load_saga_state("order-1") is None
                await scenarios.save(s, "AcmeSaga")
            await s.update_step_state("order-1", "s1", SagaStepStatus.FAILED)
            assert await s.delete_saga_state("order-1") is True  # cascades to its steps

        # Running the upgrade again is a no-op that keeps the data.
        async with _storage(isolated_postgres_url) as s:
            with tenant_scope("acme"):
                assert (await s.load_saga_state("order-1"))["saga_name"] == "AcmeSaga"
            with system_scope():
                assert await s.count() == 1

        conn = await asyncpg.connect(isolated_postgres_url)
        try:
            keys = await conn.fetch(
                "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
                "WHERE conrelid IN ('sagas'::regclass, 'saga_steps'::regclass) "
                "AND contype IN ('p', 'u', 'f')"
            )
            definitions = {r["conname"]: r["def"] for r in keys}
            assert definitions["sagas_pkey"] == "PRIMARY KEY (tenant_id, saga_id)"
            assert "(tenant_id, saga_id)" in definitions["saga_steps_tenant_saga_fkey"]
            assert definitions["saga_steps_tenant_step_key"] == (
                "UNIQUE (tenant_id, saga_id, step_name)"
            )
            assert len(definitions) == 4  # plus saga_steps_pkey; legacy keys are gone
            remaining_steps = await conn.fetchval("SELECT COUNT(*) FROM saga_steps")
            assert remaining_steps == 1  # only acme's step remains
        finally:
            await conn.close()
