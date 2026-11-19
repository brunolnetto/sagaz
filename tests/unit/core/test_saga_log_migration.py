"""``sagaz migrate unify``: the old layout into the unified saga log (ADR-041, #464)."""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from sagaz.choreography import ChoreographyEngine, ChoreographyTracker, EventBus
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.cli.app import cli
from sagaz.core.config import SagaConfig
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
from sagaz.core.storage.event_store.sqlite import SQLiteEventStore
from sagaz.core.storage.saga_log import (
    InMemorySagaLogStore,
    SnapshotKind,
)
from sagaz.core.storage.saga_log.migrate import read_old_tables, unify
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore
from sagaz.core.tenant import system_scope, tenant_scope
from tests.unit.core.test_event_sourcing import make_saga
from tests.unit.test_choreography_compensation import Inventory, Orders, Payments, Shipping


async def build_old_layout(path: str) -> None:
    """One SQLite database with every pre-ADR-041 table."""
    async with SQLiteSagaStorage(path) as storage, SQLiteEventStore(path) as events:
        await fill_old_layout(storage, events, SQLiteParticipantState(path))


async def fill_old_layout(storage, events, state) -> None:
    """Fill the old tables with real sagaz code: orchestrated sagas (one event-sourced),
    choreographed transactions with a tracker and durable participant state."""
    config = SagaConfig(storage=storage, metrics=False, logging=False)
    saga = make_saga(events, threshold=3)
    saga._config = config
    await saga.run({"order_id": "o-1"}, saga_id="orch-ok")
    failing = make_saga(events, fail_charge=True)
    failing._config = config
    with pytest.raises(ValueError):
        await failing.run({"order_id": "o-2"}, saga_id="orch-bad", tenant_context="acme")

    bus = EventBus()
    engine = ChoreographyEngine(bus, completion_events={"order.shipped"}, state=state)
    tracker = ChoreographyTracker(bus, storage, completion_events={"order.shipped"})
    orders = Orders(name="orders")
    for participant in (orders, Inventory(), Payments(), Shipping()):
        engine.register(participant)
    await tracker.start()
    await engine.start()
    await orders.begin("order.created", {"order_id": "c-ok", "amount": 40}, correlation_id="c-ok")
    await orders.begin(
        "order.created", {"order_id": "c-bad", "amount": 500}, correlation_id="c-bad"
    )
    await engine.stop()
    await tracker.stop()

    # Left pending with a deadline: nobody handles inventory.reserved here,
    # so Inventory's reservation stays recorded for compensation.
    bus = EventBus()
    engine = ChoreographyEngine(bus, completion_events={"order.shipped"}, state=state)
    tracker = ChoreographyTracker(bus, storage, completion_events={"order.shipped"})
    orders = Orders(name="orders")
    for participant in (orders, Inventory()):
        engine.register(participant)
    await tracker.start()
    await engine.start()
    await orders.begin(
        "order.created",
        {"order_id": "c-late", "amount": 40},
        correlation_id="c-late",
        deadline=3600,
    )
    await engine.stop()
    await state.close()


def migrate(path: str, *extra: str):
    return CliRunner().invoke(cli, ["migrate", "unify", "--source", f"sqlite://{path}", *extra])


@pytest.fixture
def old_db(tmp_path):
    path = str(tmp_path / "sagaz.db")
    asyncio.run(build_old_layout(path))
    return path


async def _read(path: str):
    async with SQLiteSagaLogStore(path) as log:
        with system_scope():
            transactions = {t.transaction_id: t for t in await log.list_transactions()}
            events = {tid: await log.events(tid) for tid in transactions}
            activities = {tid: await log.activities(tid) for tid in transactions}
            snapshot = await log.latest_snapshot("orch-ok", SnapshotKind.PROJECTION)
        return transactions, events, activities, snapshot


def test_unify_copies_every_old_table_once(old_db):
    dry = migrate(old_db, "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "Would copy" in dry.output

    result = migrate(old_db)
    assert result.exit_code == 0, result.output
    assert "orchestrated transactions: 2" in result.output
    assert "choreographed transactions: 3" in result.output

    transactions, events, activities, snapshot = asyncio.run(_read(old_db))
    ok, bad = transactions["orch-ok"], transactions["orch-bad"]
    assert (ok.coordination, ok.status, ok.flow) == ("orchestrated", "completed", "order")
    assert (bad.status, bad.tenant_id) == ("rolled_back", "acme")
    assert [e.event_type for e in events["orch-ok"]][0] == "SagaStarted"
    assert {e.kind for e in events["orch-ok"]} == {"lifecycle"}
    assert {a.name for a in activities["orch-ok"]} >= {"reserve", "charge"}
    assert snapshot is not None

    c_ok, c_bad = transactions["c-ok"], transactions["c-bad"]
    assert (c_ok.coordination, c_ok.status, c_ok.flow) == (
        "choreographed",
        "completed",
        "order.created",
    )
    assert (c_ok.initiator, c_bad.status) == ("orders", "compensated")
    kinds = [e.kind for e in events["c-bad"]]
    assert {"compensate", "compensated"} <= set(kinds)
    caused = [e for e in events["c-ok"] if e.causation_id]
    assert caused
    assert all(e.source for e in caused)
    markers = [a for a in activities["c-bad"] if a.name == "__transaction__"]
    assert {(m.participant, m.status) for m in markers} >= {("inventory", "compensated")}
    assert any(a.status == "completed" and a.triggered_by for a in activities["c-late"])

    again = migrate(old_db)
    assert again.exit_code == 0, again.output
    _, events_again, activities_again, _ = asyncio.run(_read(old_db))
    assert {k: len(v) for k, v in events_again.items()} == {k: len(v) for k, v in events.items()}
    assert {k: len(v) for k, v in activities_again.items()} == {
        k: len(v) for k, v in activities.items()
    }


def test_deliveries_and_deadlines_move_over(old_db):
    migrate(old_db)

    async def check():
        async with SQLiteSagaLogStore(old_db) as log:
            assert not await log.claim_delivery("inventory", await _some_event(old_db))
            from datetime import UTC, datetime, timedelta

            with system_scope():
                due = await log.claim_due_deadlines(
                    {"orders"}, datetime.now(UTC) + timedelta(days=1), timedelta(seconds=1)
                )
            assert [d.transaction_id for d in due] == ["c-late"]

    asyncio.run(check())


async def _some_event(path: str) -> str:
    tables = await read_old_tables(f"sqlite://{path}")
    return next(
        r["event_id"] for r in tables["choreography_deliveries"] if r["participant"] == "inventory"
    )


async def test_nothing_to_migrate():
    report = await unify(InMemorySagaStorage(), InMemorySagaLogStore(), {})
    assert not report.counts
    assert await read_old_tables("memory://") == {}


def test_empty_database(tmp_path):
    path = tmp_path / "empty.db"
    path.touch()
    result = migrate(str(path))
    assert result.exit_code == 0, result.output
    assert "nothing to migrate" in result.output


async def test_consumer_inbox_rows_become_deliveries():
    log = InMemorySagaLogStore()
    tables = {"consumer_inbox": [{"consumer_name": "billing", "event_id": "e-9"}]}
    report = await unify(InMemorySagaStorage(), log, tables)
    assert report.counts["deliveries"] == 1
    with tenant_scope("default"):
        assert not await log.claim_delivery("billing", "e-9")
