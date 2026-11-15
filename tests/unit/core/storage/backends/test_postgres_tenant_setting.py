"""The per-acquisition tenant setting is skipped only when provably redundant (#405)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sagaz.core.storage.backends.postgresql import _tenancy
from sagaz.core.storage.backends.postgresql._tenancy import (
    POOL_OPTIONS,
    apply_scope,
    reset_to_default_tenant,
)
from sagaz.core.tenant import system_scope, tenant_scope


class FakeConnection:
    """Records SQL; stands in for an asyncpg connection."""

    def __init__(self) -> None:
        self.sql: list[tuple] = []

    async def execute(self, query, *args):
        self.sql.append((query, *args))

    def get_reset_query(self) -> str:
        return "SELECT pg_advisory_unlock_all();\nCLOSE ALL;\nUNLISTEN *;\nRESET ALL;\n"

    def set_calls(self) -> list:
        return [args for _query, *args in self.sql if "set_config" in _query]


class Proxy:
    """Like asyncpg's PoolConnectionProxy: wraps the raw connection in ``_con``."""

    def __init__(self, con) -> None:
        self._con = con

    async def execute(self, query, *args):
        await self._con.execute(query, *args)


async def test_default_tenant_is_set_once_per_connection():
    conn = FakeConnection()
    await apply_scope(conn)
    await apply_scope(conn)
    assert conn.set_calls() == [["default"]]


async def test_other_tenants_are_set_every_time():
    conn = FakeConnection()
    with tenant_scope("acme"):
        await apply_scope(conn)
        await apply_scope(conn)
    with system_scope():
        await apply_scope(conn)
    assert conn.set_calls() == [["acme"], ["acme"], ["*"]]


async def test_default_is_set_again_after_another_tenant():
    conn = FakeConnection()
    await apply_scope(conn)  # set, now known default
    with tenant_scope("acme"):
        await apply_scope(conn)  # acme: no longer known default
    await apply_scope(conn)  # must set default again
    await apply_scope(conn)  # known default again: skipped
    assert conn.set_calls() == [["default"], ["acme"], ["default"]]


async def test_pool_reset_restores_the_default_in_the_same_round_trip():
    conn = FakeConnection()
    with tenant_scope("acme"):
        await apply_scope(conn)

    await reset_to_default_tenant(conn)

    ((reset_sql, *_),) = conn.sql[1:]  # exactly one statement batch for the reset
    assert reset_sql.startswith(conn.get_reset_query())
    assert reset_sql.endswith("SELECT set_config('app.tenant_id', 'default', false);")
    await apply_scope(conn)  # default after the reset: no round trip
    assert len(conn.sql) == 2


async def test_proxies_are_tracked_by_their_raw_connection():
    raw = FakeConnection()
    await reset_to_default_tenant(raw)  # the pool's reset receives the raw connection
    await apply_scope(Proxy(raw))  # acquisition hands out a proxy
    assert len(raw.sql) == 1  # only the reset batch; no set_config on acquire


async def test_unknown_connections_are_always_set():
    released = Proxy(None)  # a released proxy no longer wraps a connection
    released.execute = AsyncMock()
    await apply_scope(released)
    released.execute.assert_awaited_once()


@pytest.mark.parametrize(
    ("pool_kwargs", "expected_reset"),
    [({}, reset_to_default_tenant), ({"reset": "custom"}, "custom")],
)
async def test_saga_storage_pools_use_the_tenant_reset(pool_kwargs, expected_reset):
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    storage = PostgreSQLSagaStorage("postgresql://x/y", **pool_kwargs)
    with patch("asyncpg.create_pool", AsyncMock(side_effect=RuntimeError("stop"))) as create:
        with pytest.raises(Exception, match="stop"):
            await storage._get_pool()
    assert create.call_args.kwargs["reset"] == expected_reset


async def test_outbox_pools_use_the_tenant_reset():
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

    with patch("asyncpg.create_pool", AsyncMock(side_effect=RuntimeError("stop"))) as create:
        with pytest.raises(RuntimeError, match="stop"):
            await PostgreSQLOutboxStorage("postgresql://x/y").initialize()
    assert create.call_args.kwargs["reset"] is reset_to_default_tenant


def test_pool_options():
    assert {"reset": reset_to_default_tenant} == POOL_OPTIONS
    assert _tenancy._raw_connection(Proxy("raw")) == "raw"


async def test_acquire_scoped_applies_the_scope():
    from contextlib import asynccontextmanager

    from sagaz.core.storage.backends.postgresql._tenancy import acquire_scoped

    conn = FakeConnection()

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield conn

    with tenant_scope("acme"):
        async with acquire_scoped(Pool()) as acquired:
            assert acquired is conn
    assert conn.set_calls() == [["acme"]]
