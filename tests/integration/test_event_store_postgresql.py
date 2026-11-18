"""The PostgreSQL event store with real sagas (ADR-033, #57).

Runs against the PostgreSQL container, or the server in ``SAGAZ_TEST_POSTGRES_URL``,
in a database of its own.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from sagaz import Saga
from sagaz.core.config import SagaConfig
from sagaz.core.events import StepExecuted
from sagaz.core.storage.event_store.postgresql import PostgreSQLEventStore
from sagaz.core.tenant import tenant_scope
from sagaz.projections import build_projection, load_projection

asyncpg = pytest.importorskip("asyncpg")

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]


@pytest.fixture(scope="module")
def database_url(postgres_container):
    psycopg2 = pytest.importorskip("psycopg2")
    base = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    name = f"sagaz_events_{uuid4().hex[:8]}"

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
async def store(database_url):
    async with PostgreSQLEventStore(database_url) as event_store:
        yield event_store


def chain_saga(steps: int, store, threshold: int, storage=None) -> Saga:
    """An imperative saga of ``steps`` chained steps, each adding one context key."""
    config = SagaConfig(
        storage=storage,
        storage_strategy="event_sourced",
        event_store=store,
        snapshot_threshold=threshold,
        metrics=False,
        logging=False,
    )
    saga = Saga(name="chain", config=config)
    for i in range(steps):

        async def step(ctx, i=i):
            return {f"k{i}": i}

        saga.add_step(f"s{i}", step, depends_on=[f"s{i - 1}"] if i else None)
    return saga


async def test_100_events_project_to_the_stored_state(store, database_url):
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    async with PostgreSQLSagaStorage(database_url) as storage:
        saga_id = f"hundred-{uuid4().hex[:6]}"
        await chain_saga(98, store, threshold=50, storage=storage).run({}, saga_id=saga_id)
        events = await store.load_stream(saga_id)
        stored_state = await storage.load_saga_state(saga_id)

    assert [e.sequence for e in events] == list(range(1, 101))
    state = await load_projection(store, saga_id)
    assert state == build_projection(saga_id, events)
    assert state.status == stored_state["status"] == "completed"
    assert all(stored_state["context"][key] == value for key, value in state.context.items())
    assert len(state.steps) == 98
    assert (await store.load_latest_snapshot(saga_id)).sequence == 100


async def test_load_uses_the_snapshot_and_the_tail(store, monkeypatch):
    saga_id = f"tail-{uuid4().hex[:6]}"
    await chain_saga(11, store, threshold=10).run({}, saga_id=saga_id)  # 13 events

    tails = []
    original = store.load_stream_after

    async def spy(saga, after):
        tail = await original(saga, after)
        tails.append((after, len(tail)))
        return tail

    monkeypatch.setattr(store, "load_stream_after", spy)
    state = await load_projection(store, saga_id)

    assert tails == [(10, 3)]
    assert state == build_projection(saga_id, await store.load_stream(saga_id))
    assert (state.status, state.last_sequence) == ("completed", 13)


async def test_concurrent_writers_never_share_a_sequence(store, database_url):
    saga_id = f"race-{uuid4().hex[:6]}"
    async with PostgreSQLEventStore(database_url) as other:
        await asyncio.gather(
            *(
                (store if i % 2 else other).append(StepExecuted(saga_id, step_name=str(i)))
                for i in range(40)
            )
        )
    assert [e.sequence for e in await store.load_stream(saga_id)] == list(range(1, 41))


async def test_row_level_security_isolates_tenants(store, database_url):
    saga_id = f"rls-{uuid4().hex[:6]}"
    for tenant in ("acme", "globex"):
        with tenant_scope(tenant):
            await store.append(StepExecuted(saga_id, tenant_id=tenant))

    role = f"sagaz_app_{uuid4().hex[:6]}"
    admin = await asyncpg.connect(database_url)
    try:
        await admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD 'app'")
        await admin.execute(f"GRANT SELECT ON saga_events TO {role}")
        user, rest = database_url.split("://", 1)[1].split("@", 1)
        app = await asyncpg.connect(f"postgresql://{role}:app@{rest}")
        try:
            await app.execute("SELECT set_config('app.tenant_id', 'acme', false)")
            tenants = await app.fetch(
                "SELECT tenant_id FROM saga_events WHERE saga_id = $1", saga_id
            )
        finally:
            await app.close()
        await admin.execute(f"REVOKE ALL ON saga_events FROM {role}")
        await admin.execute(f"DROP ROLE {role}")
    finally:
        await admin.close()
    assert [row["tenant_id"] for row in tenants] == ["acme"]
