"""Skipping the default tenant's set_config never weakens isolation (#405).

A one-connection pool forces every operation onto the same session, so a
connection that served another tenant is reused for the default tenant. The
application connects as an ordinary role, so row-level security applies.
"""

from __future__ import annotations

import pytest

from sagaz.core.storage.backends.postgresql._tenancy import _SET_TENANT
from sagaz.core.tenant import tenant_scope
from sagaz.core.types import SagaStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _save(storage, saga_id, tenant=None):
    if tenant is None:
        await storage.save_saga_state(saga_id, "S", SagaStatus.COMPLETED, [], {"id": saga_id})
        return
    with tenant_scope(tenant):
        await storage.save_saga_state(saga_id, "S", SagaStatus.COMPLETED, [], {"id": saga_id})


@pytest.fixture
async def storage(app_role_url):
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    async with PostgreSQLSagaStorage(app_role_url, pool_min_size=1, pool_max_size=1) as s:
        yield s


async def test_connection_released_by_a_tenant_serves_the_default_tenant(storage):
    await _save(storage, "d1")
    await _save(storage, "a1", "acme")

    # Same (only) connection, now for the default tenant.
    assert await storage.load_saga_state("a1") is None
    assert [s["saga_id"] for s in await storage.list_sagas()] == ["d1"]
    await _save(storage, "d2")  # passes the RLS WITH CHECK as the default tenant
    with tenant_scope("acme"):
        assert [s["saga_id"] for s in await storage.list_sagas()] == ["a1"]

    pool = await storage._get_pool()
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT current_setting('app.tenant_id', true)") == "default"


async def test_default_tenant_sends_no_set_config_once_known(storage, monkeypatch):
    from asyncpg.connection import Connection

    await _save(storage, "warm")  # first use of the connection sets the default once
    sent = []
    original = Connection.execute

    async def recording(self, query, *args, **kwargs):
        sent.append(query)
        return await original(self, query, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", recording)

    await _save(storage, "d1")
    await storage.load_saga_state("d1")
    assert _SET_TENANT not in sent

    await _save(storage, "a1", "acme")
    assert sent.count(_SET_TENANT) == 1  # a tenant is set on its acquisition
    sent.clear()
    await storage.load_saga_state("d1")  # default again, after the pool's reset
    assert _SET_TENANT not in sent
