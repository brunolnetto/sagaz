"""PostgreSQL row-level security on the outbox tables (ADR-020).

The storage filters by tenant itself, so these tests bypass it: they create an
ordinary role (``NOSUPERUSER NOBYPASSRLS``) and prove with raw SQL that the
database alone keeps tenants apart. They also upgrade a pre-tenant
``saga_outbox`` and check its rows become the default tenant's. Each test uses
a throwaway database, so the shared container is left untouched.
"""

from __future__ import annotations

import json
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest

from sagaz.core.outbox.types import OutboxEvent
from sagaz.core.tenant import system_scope, tenant_scope

pytestmark = pytest.mark.integration

asyncpg = pytest.importorskip("asyncpg")

LEGACY_OUTBOX = """
CREATE TABLE saga_outbox (
    event_id UUID PRIMARY KEY,
    saga_id VARCHAR(255) NOT NULL,
    aggregate_type VARCHAR(255) NOT NULL DEFAULT 'saga',
    aggregate_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    headers JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    worker_id VARCHAR(255)
);
"""


def _with_database(dsn: str, database: str, user: str | None = None, password: str = "") -> str:
    parts = urlsplit(dsn)
    netloc = parts.netloc
    if user is not None:
        netloc = f"{user}:{password}@{netloc.rsplit('@', 1)[1]}"
    return urlunsplit((parts.scheme, netloc, f"/{database}", parts.query, parts.fragment))


@pytest.fixture
async def database(postgres_connection_string):
    """A fresh database (DSN as the container superuser) and a cleanup hook."""
    if not postgres_connection_string:
        pytest.skip("PostgreSQL container not available")
    name = f"rls_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(postgres_connection_string)
    await admin.execute(f"CREATE DATABASE {name}")
    roles: list[str] = []
    try:
        yield _with_database(postgres_connection_string, name), roles
    finally:
        await admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        for role in roles:
            await admin.execute(f"DROP ROLE IF EXISTS {role}")
        await admin.close()


async def _app_role(dsn: str, roles: list[str]) -> str:
    """Create an ordinary role allowed to use the outbox tables; return its DSN."""
    role = f"app_{uuid.uuid4().hex[:12]}"
    roles.append(role)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'pw' NOSUPERUSER NOBYPASSRLS")
        await conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}")
    finally:
        await conn.close()
    return _with_database(dsn, urlsplit(dsn).path.lstrip("/"), user=role, password="pw")


async def _storage(dsn: str):
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    storage = PostgreSQLOutboxStorage(connection_string=dsn, pool_min_size=1, pool_max_size=2)
    await storage.initialize()
    return storage


async def _connect_as(dsn: str, tenant: str | None):
    conn = await asyncpg.connect(dsn)
    if tenant is not None:
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", tenant)
    return conn


async def _insert_raw(conn, tenant: str) -> None:
    await conn.execute(
        "INSERT INTO saga_outbox (event_id, saga_id, aggregate_id, event_type, payload, tenant_id) "
        "VALUES ($1, 's', 's', 'Evt', '{}', $2)",
        uuid.uuid4(),
        tenant,
    )


class TestRowLevelSecurity:
    async def test_database_isolates_tenants_for_an_ordinary_role(self, database):
        dsn, roles = database
        storage = await _storage(dsn)
        try:
            for tenant in ("tenant-a", "tenant-b"):
                with tenant_scope(tenant):
                    await storage.insert(OutboxEvent(saga_id="s", event_type="Evt", payload={}))
        finally:
            await storage.close()
        app_dsn = await _app_role(dsn, roles)

        conn = await _connect_as(app_dsn, "tenant-a")
        try:
            rows = await conn.fetch("SELECT tenant_id FROM saga_outbox")
            assert [r["tenant_id"] for r in rows] == ["tenant-a"]
            assert (
                await conn.fetchval("SELECT COUNT(*) FROM saga_outbox WHERE tenant_id = 'tenant-b'")
                == 0
            )
            assert await conn.execute("UPDATE saga_outbox SET status = 'sent'") == "UPDATE 1"
            assert await conn.execute("DELETE FROM saga_outbox WHERE tenant_id = 'tenant-b'") == (
                "DELETE 0"
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await _insert_raw(conn, "tenant-b")
            await _insert_raw(conn, "tenant-a")
        finally:
            await conn.close()

        # No tenant set: the role only sees the default tenant (none here).
        conn = await _connect_as(app_dsn, None)
        try:
            assert await conn.fetchval("SELECT COUNT(*) FROM saga_outbox") == 0
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await _insert_raw(conn, "tenant-a")
        finally:
            await conn.close()

        # The system scope ('*'), used by the outbox worker, sees every tenant.
        conn = await _connect_as(app_dsn, "*")
        try:
            rows = await conn.fetch("SELECT tenant_id FROM saga_outbox ORDER BY tenant_id")
            assert [r["tenant_id"] for r in rows] == ["tenant-a", "tenant-a", "tenant-b"]
        finally:
            await conn.close()

    async def test_storage_running_as_an_ordinary_role(self, database):
        dsn, roles = database
        await (await _storage(dsn)).close()  # create the schema as the owner
        app_dsn = await _app_role(dsn, roles)
        # initialize() re-applies DDL, which needs ownership: build the pool only.
        from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        storage = PostgreSQLOutboxStorage(app_dsn, pool_min_size=1, pool_max_size=2)
        storage._pool = await asyncpg.create_pool(app_dsn, min_size=1, max_size=2)
        try:
            with tenant_scope("tenant-a"):
                a = await storage.insert(OutboxEvent(saga_id="s", event_type="Evt", payload={}))
            with tenant_scope("tenant-b"):
                assert await storage.get_by_id(a.event_id) is None
                assert await storage.get_events_by_saga("s") == []
            with system_scope():
                claimed = await storage.claim_batch("w", batch_size=10)
            assert [e.tenant_id for e in claimed] == ["tenant-a"]
        finally:
            await storage.close()


class TestMigration:
    async def test_pre_tenant_rows_become_default(self, database):
        dsn, _ = database
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(LEGACY_OUTBOX)
            await conn.execute(
                "INSERT INTO saga_outbox (event_id, saga_id, aggregate_id, event_type, payload) "
                "VALUES ($1, 'legacy', 'legacy', 'Evt', $2)",
                uuid.uuid4(),
                json.dumps({"n": 1}),
            )
        finally:
            await conn.close()

        storage = await _storage(dsn)
        try:
            from sagaz.core.storage.backends.postgresql.outbox import OUTBOX_SCHEMA

            async with storage._pool.acquire() as conn:
                await conn.execute(OUTBOX_SCHEMA)  # idempotent: re-applying is safe
            events = await storage.get_events_by_saga("legacy")
            assert [e.tenant_id for e in events] == ["default"]
            with tenant_scope("tenant-a"):
                assert await storage.get_events_by_saga("legacy") == []
        finally:
            await storage.close()

        conn = await asyncpg.connect(dsn)
        try:
            policies = await conn.fetch(
                "SELECT tablename FROM pg_policies WHERE policyname = 'sagaz_tenant_isolation'"
            )
            forced = await conn.fetchval(
                "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'saga_outbox'"
            )
        finally:
            await conn.close()
        assert {p["tablename"] for p in policies} == {
            "saga_outbox",
            "saga_outbox_archive",
            "consumer_inbox",
        }
        assert forced is True
