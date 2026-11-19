"""PostgreSQL stores skip unchanged DDL, so a starting process never blocks writers.

Runs against the PostgreSQL container, or the server in ``SAGAZ_TEST_POSTGRES_URL``,
in a database of its own per test.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

asyncpg = pytest.importorskip("asyncpg")

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]


def _saga(url):
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    return PostgreSQLSagaStorage(url, pool_min_size=1, pool_max_size=2)


def _snapshot(url):
    from sagaz.core.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

    return PostgreSQLSnapshotStorage(url)


def _event_store(url):
    from sagaz.core.storage.event_store.postgresql import PostgreSQLEventStore

    return PostgreSQLEventStore(url)


def _participant_state(url):
    from sagaz.choreography.state.postgresql import PostgreSQLParticipantState

    return PostgreSQLParticipantState(url)


class _Outbox:
    """Adapts the outbox storage (``initialize()``) to ``_get_pool()``."""

    def __init__(self, url) -> None:
        from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        self.storage = PostgreSQLOutboxStorage(url, pool_min_size=1, pool_max_size=2)

    async def _get_pool(self):
        await self.storage.initialize()
        return self.storage._pool

    @property
    def _pool(self):
        return self.storage._pool


STORES = {
    "saga": (_saga, "sagas"),
    "snapshot": (_snapshot, "saga_snapshots"),
    "outbox": (_Outbox, "saga_outbox"),
    "event_store": (_event_store, "saga_events"),
    "choreography_state": (_participant_state, "choreography_actions"),
}


@pytest.fixture
def database_url(postgres_container):
    psycopg2 = pytest.importorskip("psycopg2")
    base = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    name = f"sagaz_ddl_{uuid4().hex[:8]}"

    def admin(sql: str) -> None:
        conn = psycopg2.connect(base)
        conn.autocommit = True
        try:
            conn.cursor().execute(sql)
        finally:
            conn.close()

    admin(f"CREATE DATABASE {name}")
    yield base.rsplit("/", 1)[0] + f"/{name}"
    admin(f"DROP DATABASE {name} WITH (FORCE)")


async def _close(store) -> None:
    pool = store._pool
    if pool is not None:
        await pool.close()


@pytest.mark.parametrize("component", sorted(STORES))
async def test_starting_on_a_current_schema_does_not_block_writers(database_url, component):
    make, table = STORES[component]
    first = make(database_url)
    await first._get_pool()
    writer = await asyncpg.connect(database_url)
    newcomer = make(database_url)
    try:
        async with writer.transaction():
            await writer.execute(f"LOCK TABLE {table} IN ROW EXCLUSIVE MODE")  # a writer
            await asyncio.wait_for(newcomer._get_pool(), timeout=5)
        version = await writer.fetchval(
            "SELECT version FROM sagaz_schema_version WHERE component = $1", component
        )
        assert version
    finally:
        await writer.close()
        await _close(first)
        await _close(newcomer)


async def test_changed_ddl_is_applied_once(database_url):
    from sagaz.core.storage.backends.postgresql._schema_version import apply_schema

    conn = await asyncpg.connect(database_url)
    try:
        sql = "CREATE TABLE IF NOT EXISTS ddl_probe (id INT)"
        assert await apply_schema(conn, "probe", sql)
        assert not await apply_schema(conn, "probe", sql)
        changed = sql + "; ALTER TABLE ddl_probe ADD COLUMN IF NOT EXISTS name TEXT"
        assert await apply_schema(conn, "probe", changed)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns WHERE table_name = 'ddl_probe'"
            )
            == 2
        )
    finally:
        await conn.close()


async def test_concurrent_first_startups_apply_the_schema_once(database_url):
    stores = [_saga(database_url) for _ in range(4)]
    try:
        await asyncio.gather(*(s._get_pool() for s in stores))
    finally:
        for store in stores:
            await _close(store)
