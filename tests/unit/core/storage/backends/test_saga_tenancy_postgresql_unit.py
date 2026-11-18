"""Tenant scoping of PostgreSQLSagaStorage queries, without a database (ADR-020).

The behaviour against a real PostgreSQL (including row-level security) is
covered by tests/integration/test_saga_tenancy_postgresql.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sagaz.core.storage.backends.postgresql._saga_query import tenant_condition
from sagaz.core.storage.backends.postgresql._saga_schema import SAGA_TABLES_SQL
from sagaz.core.tenant import system_scope, tenant_scope

pytest.importorskip("asyncpg")


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return None


@pytest.fixture
def storage():
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="DELETE 2")
    conn.fetch = AsyncMock(return_value=[{"status": "completed", "count": 2}])
    conn.fetchrow = AsyncMock(return_value={"size": 0})
    conn.fetchval = AsyncMock(return_value=3)
    pool = MagicMock()
    pool.acquire.return_value = _Acquire(conn)
    s = PostgreSQLSagaStorage("postgresql://localhost/test")
    s._pool = pool
    return s, conn


def _sql_calls(conn, method):
    return [call.args for call in getattr(conn, method).await_args_list]


def test_tenant_condition_binds_the_current_tenant():
    params: list = ["saga-1"]
    assert tenant_condition("tenant_id", params) == "tenant_id = $2"
    assert params == ["saga-1", "default"]
    with tenant_scope("acme"):
        params = []
        assert tenant_condition("s.tenant_id", params) == "s.tenant_id = $1"
        assert params == ["acme"]
    with system_scope():
        params = []
        assert tenant_condition("tenant_id", params) == "TRUE"
        assert params == []


def test_schema_upgrades_keys_and_enables_rls_for_both_tables():
    assert "PRIMARY KEY (tenant_id, saga_id)" in SAGA_TABLES_SQL
    assert "UNIQUE (tenant_id, saga_id, step_name)" in SAGA_TABLES_SQL
    for table in ("sagas", "saga_steps"):
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in SAGA_TABLES_SQL
    # Backfills run as the system scope, for this transaction only.
    assert "set_config('app.tenant_id', '*', true)" in SAGA_TABLES_SQL


@pytest.mark.asyncio
async def test_every_connection_is_scoped_and_queries_filter_by_tenant(storage):
    s, conn = storage
    with tenant_scope("acme"):
        assert (await s.get_saga_statistics())["total_sagas"] == 2
        assert await s.count() == 3
        assert await s.delete_saga_state("x") is True
    scope_calls = [c for c in _sql_calls(conn, "execute") if "set_config" in c[0]]
    assert scope_calls
    assert all(c[1] == "acme" for c in scope_calls)
    statistics_sql, *statistics_params = _sql_calls(conn, "fetch")[0]
    assert "WHERE tenant_id = $1" in statistics_sql
    assert statistics_params == ["acme"]
    count_sql, *count_params = _sql_calls(conn, "fetchval")[0]
    assert "WHERE tenant_id = $1" in count_sql
    assert count_params == ["acme"]


@pytest.mark.asyncio
async def test_system_scope_queries_span_tenants(storage):
    s, conn = storage
    with system_scope():
        assert (await s.get_saga_statistics())["total_sagas"] == 2
        assert await s.cleanup_completed_sagas(older_than=MagicMock()) == 2
    statistics_sql, *statistics_params = _sql_calls(conn, "fetch")[0]
    assert "WHERE TRUE" in statistics_sql
    assert statistics_params == []
    scope_calls = [c for c in _sql_calls(conn, "execute") if "set_config" in c[0]]
    assert all(c[1] == "*" for c in scope_calls)


def test_rows_without_tenant_column_are_the_default_tenant():
    from sagaz.core.storage.backends.postgresql._saga_rows import _PostgreSQLSagaRowMixin

    assert _PostgreSQLSagaRowMixin._row_tenant({"saga_id": "x"}) == "default"
    assert _PostgreSQLSagaRowMixin._row_tenant({"tenant_id": None}) == "default"
    assert _PostgreSQLSagaRowMixin._row_tenant({"tenant_id": "acme"}) == "acme"
