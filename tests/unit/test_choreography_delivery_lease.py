"""A delivery is reserved while its handler runs, not claimed for good (#561).

If the process dies in the handler, the reservation expires and the broker's
redelivery is handled; a duplicate arriving while it is live is dropped; once
handled, the delivery is done for good.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid4

import pytest

from sagaz.choreography import (
    COMPENSATE,
    ChoreographedSaga,
    ChoreographyEngine,
    Event,
    EventBus,
    on_event,
)
from sagaz.choreography._dispatch import LEASE_MARGIN, UNBOUNDED_LEASE, RetryDefaults
from sagaz.choreography.state import InMemoryParticipantState, ParticipantState
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.choreography.state.unified import UnifiedParticipantState
from sagaz.core.storage.saga_log import InMemorySagaLogStore, SagaLogStore
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore
from sagaz.core.tenant import tenant_scope

SHORT = timedelta(milliseconds=30)
LONG = timedelta(minutes=5)


async def expire() -> None:
    await asyncio.sleep(SHORT.total_seconds() * 2)


@pytest.fixture(params=["memory", "sqlite", "unified-memory", "unified-sqlite"])
async def state(request, tmp_path):
    kind = request.param
    if kind == "memory":
        yield InMemoryParticipantState()
        return
    if kind == "sqlite":
        sqlite_state = SQLiteParticipantState(str(tmp_path / "state.db"))
        yield sqlite_state
        await sqlite_state.close()
        return
    log = InMemorySagaLogStore() if kind == "unified-memory" else SQLiteSagaLogStore()
    yield UnifiedParticipantState(log)
    await log.close()


class LeaseContract:
    """The lease behaviour, for every participant state (subclassed per backend)."""

    async def test_a_live_reservation_drops_a_duplicate(self, state):
        assert await state.claim_delivery("inventory", "e-1", LONG)
        assert not await state.claim_delivery("inventory", "e-1", LONG)
        assert await state.claim_delivery("payments", "e-1", LONG)  # per participant

    async def test_a_finished_delivery_is_never_claimed_again(self, state):
        assert await state.claim_delivery("inventory", "e-1", SHORT)
        await state.finish_delivery("inventory", "e-1")
        await expire()
        assert not await state.claim_delivery("inventory", "e-1", SHORT)
        assert not await state.first_delivery("inventory", "e-1")

    async def test_an_expired_reservation_is_claimed_again(self, state):
        assert await state.claim_delivery("inventory", "e-1", SHORT)
        await expire()
        assert await state.claim_delivery("inventory", "e-1", LONG)
        assert not await state.claim_delivery("inventory", "e-1", LONG)

    async def test_first_delivery_still_claims_for_good(self, state):
        assert await state.first_delivery("inventory", "e-1")
        assert not await state.claim_delivery("inventory", "e-1", SHORT)
        assert await state.claim_delivery("inventory", "e-2", LONG)
        assert not await state.first_delivery("inventory", "e-2")  # reserved

    async def test_tenants_are_separate(self, state):
        with tenant_scope("acme"):
            assert await state.claim_delivery("inventory", "e-1", LONG)
            await state.finish_delivery("inventory", "e-1")
        with tenant_scope("globex"):
            assert await state.claim_delivery("inventory", "e-1", LONG)


class TestLease(LeaseContract):
    pass


# -- the defaults keep third-party stores working ------------------------------------


class OldState(InMemoryParticipantState):
    """A store written before #561: only ``first_delivery``."""

    claim_delivery = ParticipantState.claim_delivery
    finish_delivery = ParticipantState.finish_delivery


class OldLog(InMemorySagaLogStore):
    lease_delivery = SagaLogStore.lease_delivery
    finish_delivery = SagaLogStore.finish_delivery


@pytest.mark.parametrize("old", [OldState, lambda: UnifiedParticipantState(OldLog())])
async def test_stores_without_leases_deliver_at_most_once(old):
    store = old()
    assert await store.claim_delivery("inventory", "e-1", SHORT)
    await expire()
    assert not await store.claim_delivery("inventory", "e-1", SHORT)
    await store.finish_delivery("inventory", "e-1")  # no-op


# -- rows written before #561 mean "done" --------------------------------------------


async def test_old_sqlite_participant_rows_still_block_a_redelivery(tmp_path):
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE choreography_deliveries (tenant_id TEXT NOT NULL,"
            " participant TEXT NOT NULL, event_id TEXT NOT NULL, handled_at TEXT NOT NULL,"
            " PRIMARY KEY (tenant_id, participant, event_id))"
        )
        conn.execute(
            "INSERT INTO choreography_deliveries VALUES"
            " ('default', 'inventory', 'e-1', '2000-01-01T00:00:00+00:00')"
        )
    store = SQLiteParticipantState(path)
    try:
        assert not await store.claim_delivery("inventory", "e-1", SHORT)
        assert await store.claim_delivery("inventory", "e-2", SHORT)
        assert await store.prune(timedelta(days=1)) == 1  # old rows still prune by handled_at
    finally:
        await store.close()


async def test_old_sqlite_saga_log_rows_still_block_a_redelivery(tmp_path):
    path = str(tmp_path / "old-log.db")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE saga_delivery (tenant_id TEXT NOT NULL, participant TEXT NOT NULL,"
            " event_id TEXT NOT NULL, consumed_at TEXT NOT NULL,"
            " PRIMARY KEY (tenant_id, participant, event_id))"
        )
        conn.execute(
            "INSERT INTO saga_delivery VALUES"
            " ('default', 'inventory', 'e-1', '2026-01-01T00:00:00+00:00')"
        )
    log = SQLiteSagaLogStore(path)
    try:
        state = UnifiedParticipantState(log)
        assert not await state.claim_delivery("inventory", "e-1", SHORT)
        assert await state.claim_delivery("inventory", "e-2", SHORT)
    finally:
        await log.close()


# -- the lease length ----------------------------------------------------------------


def test_the_lease_covers_every_attempt():
    defaults = RetryDefaults(max_retries=2, timeout_seconds=10.0, retry_backoff_base=1.0)
    assert defaults.lease(2, 10.0) == timedelta(seconds=3 * 10 + (1 + 2) + LEASE_MARGIN)
    assert defaults.lease(0, None) == timedelta(seconds=UNBOUNDED_LEASE)
    fixed = RetryDefaults(delivery_lease=5.0)
    assert fixed.lease(3, 60.0) == fixed.lease(0, None) == timedelta(seconds=5)


# -- the engine ----------------------------------------------------------------------


class Warehouse(ChoreographedSaga):
    """Hangs on its first delivery (a process about to die), then succeeds."""

    def __init__(self) -> None:
        super().__init__(name="warehouse")
        self.started = asyncio.Event()
        self.hang = True
        self.runs = 0

    @on_event("order.created", max_retries=0)
    async def reserve(self, event: Event) -> None:
        self.runs += 1
        self.started.set()
        if self.hang:
            await asyncio.Event().wait()


class Broken(ChoreographedSaga):
    def __init__(self) -> None:
        super().__init__(name="broken")
        self.runs = 0

    @on_event("order.created", max_retries=0)
    async def reserve(self, event: Event) -> None:
        self.runs += 1
        msg = "out of stock"
        raise RuntimeError(msg)


async def test_a_delivery_whose_handler_died_is_handled_after_the_lease():
    bus = EventBus()
    engine = ChoreographyEngine(
        bus, state=InMemoryParticipantState(), delivery_lease=SHORT.total_seconds()
    )
    warehouse = Warehouse()
    engine.register(warehouse)
    await engine.start()
    event = Event("order.created", {"order_id": "o-1"}, saga_id="t-1")

    crashed = asyncio.create_task(bus.publish(event))
    await warehouse.started.wait()
    await bus.publish(event)  # a duplicate while the handler runs: dropped
    assert warehouse.runs == 1
    crashed.cancel()  # the process dies in the handler
    with pytest.raises(asyncio.CancelledError):
        await crashed

    await bus.publish(event)  # redelivered before the reservation expired: dropped
    assert warehouse.runs == 1
    await expire()
    warehouse.hang = False
    await bus.publish(event)  # redelivered after: handled
    assert warehouse.runs == 2
    await expire()
    await bus.publish(event)  # handled for good
    assert warehouse.runs == 2
    await engine.stop()


async def test_a_reported_failure_finishes_the_delivery():
    bus = EventBus()
    engine = ChoreographyEngine(
        bus, state=InMemoryParticipantState(), delivery_lease=SHORT.total_seconds()
    )
    broken = Broken()
    engine.register(broken)
    await engine.start()
    event = Event("order.created", {"order_id": "o-1"}, saga_id="t-1")
    await bus.publish(event)
    assert [e.event_type for e in bus.published].count(COMPENSATE) == 1
    await expire()
    await bus.publish(event)
    assert broken.runs == 1
    await engine.stop()


# -- PostgreSQL ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_database(postgres_container):
    """A factory of fresh databases on the test server, dropped at the end."""
    psycopg2 = pytest.importorskip("psycopg2")
    base = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    names: list[str] = []

    def admin(sql: str) -> None:
        conn = psycopg2.connect(base)
        conn.autocommit = True
        try:
            conn.cursor().execute(sql)
        finally:
            conn.close()

    def create(setup: str | None = None) -> str:
        name = f"sagaz_lease_{uuid4().hex[:8]}"
        admin(f"CREATE DATABASE {name}")
        names.append(name)
        url = base.rsplit("/", 1)[0] + f"/{name}"
        if setup:
            conn = psycopg2.connect(url)
            conn.autocommit = True
            try:
                conn.cursor().execute(setup)
            finally:
                conn.close()
        return url

    yield create
    for name in names:
        admin(f"DROP DATABASE {name} WITH (FORCE)")


def _pg_store(kind: str, url: str) -> tuple[ParticipantState, Callable[[], Awaitable[None]]]:
    """The participant state, and how to close it."""
    pytest.importorskip("asyncpg")
    if kind == "postgresql":
        from sagaz.choreography.state.postgresql import PostgreSQLParticipantState

        store = PostgreSQLParticipantState(url)
        return store, store.close
    from sagaz.core.storage.saga_log.postgresql import PostgreSQLSagaLogStore

    log = PostgreSQLSagaLogStore(url)
    return UnifiedParticipantState(log), log.close


_OLD_PG_TABLES = {
    "postgresql": "CREATE TABLE choreography_deliveries (tenant_id TEXT NOT NULL DEFAULT"
    " 'default', participant TEXT NOT NULL, event_id TEXT NOT NULL, handled_at TIMESTAMPTZ"
    " NOT NULL, PRIMARY KEY (tenant_id, participant, event_id));"
    " INSERT INTO choreography_deliveries VALUES ('default', 'inventory', 'e-1', NOW());",
    "unified-postgresql": "CREATE TABLE saga_delivery (tenant_id TEXT NOT NULL DEFAULT"
    " 'default', participant TEXT NOT NULL, event_id TEXT NOT NULL, consumed_at TIMESTAMPTZ"
    " NOT NULL, PRIMARY KEY (tenant_id, participant, event_id));"
    " INSERT INTO saga_delivery VALUES ('default', 'inventory', 'e-1', NOW());",
}


@pytest.mark.integration
@pytest.mark.xdist_group(name="postgres")
class TestPostgreSQLLease(LeaseContract):
    @pytest.fixture(params=["postgresql", "unified-postgresql"])
    async def state(self, request, pg_database):
        store, close = _pg_store(request.param, pg_database())
        yield store
        await close()

    @pytest.mark.parametrize("kind", ["postgresql", "unified-postgresql"])
    async def test_old_rows_still_block_a_redelivery(self, kind, pg_database):
        store, close = _pg_store(kind, pg_database(_OLD_PG_TABLES[kind]))
        try:
            assert not await store.claim_delivery("inventory", "e-1", SHORT)
            assert await store.claim_delivery("inventory", "e-2", SHORT)
        finally:
            await close()

    @pytest.mark.parametrize("kind", ["postgresql", "unified-postgresql"])
    async def test_concurrent_claims_take_one_reservation(self, kind, pg_database):
        store, close = _pg_store(kind, pg_database())
        try:
            assert await store.claim_delivery("inventory", "e-1", SHORT)
            await expire()
            won = await asyncio.gather(
                *(store.claim_delivery("inventory", "e-1", LONG) for _ in range(8))
            )
            assert won.count(True) == 1
        finally:
            await close()
