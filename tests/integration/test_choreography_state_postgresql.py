"""The PostgreSQL participant state (#448).

Runs against the PostgreSQL container, or the server in ``SAGAZ_TEST_POSTGRES_URL``,
in a database of its own.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from sagaz.choreography import COMPENSATE, Event
from sagaz.choreography.state.postgresql import PostgreSQLParticipantState
from tests.unit.test_choreography_state import TestContract, created, run_inventory

asyncpg = pytest.importorskip("asyncpg")

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]

__all__ = ["TestContract"]  # re-run the shared contract against PostgreSQL


@pytest.fixture(scope="module")
def database_url(postgres_container):
    psycopg2 = pytest.importorskip("psycopg2")
    base = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    name = f"sagaz_chor_{uuid4().hex[:8]}"

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


@pytest.fixture
async def state(database_url):
    pg_state = PostgreSQLParticipantState(database_url)
    yield pg_state
    async with pg_state._lock:
        pool = pg_state._pool
    if pool is not None:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE choreography_actions, choreography_transactions, choreography_deliveries"
            )
    await pg_state.close()


async def test_a_restarted_participant_compensates_earlier_actions(database_url, state):
    await run_inventory(database_url, created("t-restart"))
    after = await run_inventory(database_url, Event(COMPENSATE, saga_id="t-restart"))
    assert after.released == ["o-1"]


async def test_an_action_never_lands_after_the_transaction_ended(state):
    """record_action and finish of one transaction are serialized."""
    events = [created("t-race", str(i)) for i in range(30)]
    await asyncio.gather(
        *(state.record_action("inventory", e) for e in events[:15]),
        state.finish("inventory", "t-race", compensated=True),
        *(state.record_action("inventory", e) for e in events[15:]),
    )
    # Whatever the first finish() did not return was never recorded: nothing is
    # left behind for a later compensation to miss.
    assert await state.finish("inventory", "t-race", compensated=True) == []


async def test_row_level_security_isolates_tenants(database_url, state):
    from sagaz.core.tenant import tenant_scope

    for tenant in ("acme", "globex"):
        with tenant_scope(tenant):
            await state.finish("inventory", "t-rls", compensated=True)

    role = f"sagaz_app_{uuid4().hex[:6]}"
    admin = await asyncpg.connect(database_url)
    try:
        await admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'app'")
        await admin.execute(f"GRANT SELECT ON choreography_transactions TO {role}")
        rest = database_url.split("://", 1)[1].split("@", 1)[1]
        app = await asyncpg.connect(f"postgresql://{role}:app@{rest}")
        try:
            await app.execute("SELECT set_config('app.tenant_id', 'acme', false)")
            rows = await app.fetch(
                "SELECT tenant_id FROM choreography_transactions WHERE correlation_id = 't-rls'"
            )
        finally:
            await app.close()
        await admin.execute(f"REVOKE ALL ON choreography_transactions FROM {role}")
        await admin.execute(f"DROP ROLE {role}")
    finally:
        await admin.close()
    assert [row["tenant_id"] for row in rows] == ["acme"]
