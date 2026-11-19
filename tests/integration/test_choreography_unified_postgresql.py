"""Choreography on the PostgreSQL unified saga log (ADR-041 phase 3, #466).

Re-runs the unit scenarios against PostgreSQL: the outbox is ``saga_outbox``
and replicas share state through the database.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from sagaz.core.storage.saga_log.postgresql import PostgreSQLSagaLogStore
from tests.unit.test_choreography_unified import TestAtomicity, TestDurability, TestFlows

pytest.importorskip("asyncpg")

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]

__all__ = ["TestAtomicity", "TestDurability", "TestFlows"]


@pytest.fixture(scope="module")
def database_url(postgres_container):
    psycopg2 = pytest.importorskip("psycopg2")
    base = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    name = f"sagaz_cu_{uuid4().hex[:8]}"

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
async def log(database_url):
    store = PostgreSQLSagaLogStore(database_url)
    yield store
    if store._pool is not None:
        async with store._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE saga_transaction, saga_activity, saga_log_event, saga_delivery,"
                " saga_deadline, saga_outbox"
            )
    await store.close()
