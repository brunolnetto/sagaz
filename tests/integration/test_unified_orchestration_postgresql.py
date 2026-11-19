"""Orchestrated sagas on the PostgreSQL unified saga log (ADR-041 phase 2, #465).

Re-runs the unit scenarios (``TestDeclarative``, ``TestClassic``) against the
PostgreSQL store, in a database of its own.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from sagaz.core.storage.saga_log.postgresql import PostgreSQLSagaLogStore
from tests.unit.core.test_unified_orchestration import TestClassic, TestDeclarative

pytest.importorskip("asyncpg")

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]

__all__ = ["TestClassic", "TestDeclarative"]


@pytest.fixture(scope="module")
def database_url(postgres_container):
    psycopg2 = pytest.importorskip("psycopg2")
    base = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    name = f"sagaz_uo_{uuid4().hex[:8]}"

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
                "TRUNCATE saga_transaction, saga_activity, saga_log_event, saga_snapshot"
            )
    await store.close()
