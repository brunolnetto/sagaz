"""The unified saga log store contract (ADR-041, #464).

``TestContract`` runs on the in-memory and SQLite stores here, and on
PostgreSQL in ``tests/integration/test_saga_log_postgresql.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sagaz.core.storage.saga_log import (
    Activity,
    ConcurrencyError,
    Coordination,
    Deadline,
    EventKind,
    InMemorySagaLogStore,
    LogEvent,
    LogWrite,
    Participant,
    Snapshot,
    SnapshotKind,
    StatusChange,
    Transaction,
    create_saga_log_store,
)
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore
from sagaz.core.tenant import system_scope, tenant_scope

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield InMemorySagaLogStore()
        return
    sqlite_store = SQLiteSagaLogStore(str(tmp_path / "log.db"))
    yield sqlite_store
    await sqlite_store.close()


def tx(tid="t-1", flow="order", coordination=Coordination.ORCHESTRATED, **kw) -> Transaction:
    return Transaction(tid, flow, coordination, initiator="orders", started_at=T0, **kw)


def event(tid="t-1", event_type="SagaStarted", **kw) -> LogEvent:
    kw.setdefault("kind", EventKind.LIFECYCLE)
    return LogEvent(tid, event_type, source="orders", occurred_at=T0, **kw)


def activity(tid="t-1", aid="a-1", status="executing", **kw) -> Activity:
    return Activity(tid, aid, "inventory", "reserve", status=status, started_at=T0, **kw)


class TestContract:
    async def test_a_transaction_its_events_and_activities(self, store):
        stored = await store.write(
            LogWrite(
                transaction=tx(context={"order_id": "o-1"}),
                events=[event(), event(event_type="StepExecuted", payload={"step": "reserve"})],
                activities=[activity(result={"r": 1})],
            )
        )
        assert [e.sequence for e in stored] == [1, 2]
        transaction = await store.get_transaction("t-1")
        assert (transaction.flow, transaction.coordination) == ("order", "orchestrated")
        assert (transaction.context, transaction.version) == ({"order_id": "o-1"}, 1)
        assert transaction.started_at == T0
        events = await store.events("t-1")
        assert [(e.sequence, e.event_type) for e in events] == [
            (1, "SagaStarted"),
            (2, "StepExecuted"),
        ]
        assert events[1].payload == {"step": "reserve"}
        assert events[1].occurred_at == T0
        assert [e.sequence for e in await store.events("t-1", after_sequence=1)] == [2]
        (row,) = await store.activities("t-1")
        assert (row.participant, row.status, row.result) == ("inventory", "executing", {"r": 1})

    async def test_activities_are_upserted(self, store):
        await store.write(LogWrite(transaction=tx(), activities=[activity()]))
        await store.write(LogWrite(activities=[activity(status="completed", duration_ms=3.5)]))
        (row,) = await store.activities("t-1")
        assert (row.status, row.duration_ms) == ("completed", 3.5)

    async def test_status_changes_are_versioned(self, store):
        await store.write(LogWrite(transaction=tx()))
        await store.write(
            LogWrite(status=StatusChange("t-1", "completed", 1, ended_at=T0, context={"x": 1}))
        )
        transaction = await store.get_transaction("t-1")
        assert (transaction.status, transaction.version) == ("completed", 2)
        assert (transaction.ended_at, transaction.context) == (T0, {"x": 1})
        with pytest.raises(ConcurrencyError):
            await store.write(LogWrite(status=StatusChange("t-1", "failed", 1), events=[event()]))
        assert (await store.get_transaction("t-1")).status == "completed"
        assert await store.events("t-1") == []  # the batch was not applied

    async def test_a_status_change_with_the_transaction_insert(self, store):
        await store.write(LogWrite(transaction=tx(), status=StatusChange("t-1", "completed", 1)))
        assert (await store.get_transaction("t-1")).version == 2

    async def test_inserting_a_transaction_twice_keeps_the_first(self, store):
        await store.write(LogWrite(transaction=tx(flow="first")))
        await store.write(LogWrite(transaction=tx(flow="second")))
        assert (await store.get_transaction("t-1")).flow == "first"

    async def test_duplicate_event_ids_reject_the_whole_batch(self, store):
        first = event()
        await store.write(LogWrite(transaction=tx(), events=[first]))
        with pytest.raises(Exception):  # noqa: B017 - backend-specific error type
            await store.write(LogWrite(events=[event(event_type="x"), first]))
        assert [e.event_type for e in await store.events("t-1")] == ["SagaStarted"]

    async def test_sequences_are_per_transaction(self, store):
        await store.write(LogWrite(events=[event("a"), event("b"), event("a")]))
        assert [e.sequence for e in await store.events("a")] == [1, 2]
        assert [e.sequence for e in await store.events("b")] == [1]
        assert await store.get_transaction("missing") is None

    async def test_listing_transactions(self, store):
        later = T0 + timedelta(minutes=1)
        await store.write(LogWrite(transaction=tx("o-1")))
        await store.write(
            LogWrite(
                transaction=Transaction(
                    "c-1", "order.created", Coordination.CHOREOGRAPHED, started_at=later
                )
            )
        )
        assert [t.transaction_id for t in await store.list_transactions()] == ["c-1", "o-1"]
        choreographed = await store.list_transactions(coordination="choreographed")
        assert [t.transaction_id for t in choreographed] == ["c-1"]
        assert [t.transaction_id for t in await store.list_transactions(flow="order")] == ["o-1"]
        assert await store.list_transactions(status="completed") == []
        assert len(await store.list_transactions(limit=1)) == 1

    async def test_deliveries_are_claimed_once_per_participant(self, store):
        assert await store.claim_delivery("inventory", "e-1")
        assert not await store.claim_delivery("inventory", "e-1")
        assert await store.claim_delivery("payments", "e-1")

    async def test_snapshots(self, store):
        assert await store.latest_snapshot("t-1") is None
        for sequence in (10, 20):
            await store.save_snapshot(Snapshot("t-1", sequence, {"n": sequence}))
        await store.save_snapshot(Snapshot("t-1", 20, {"n": 21}))  # replaces
        await store.save_snapshot(Snapshot("t-1", 30, {"replay": True}, SnapshotKind.REPLAY))
        latest = await store.latest_snapshot("t-1")
        assert (latest.sequence, latest.state) == (20, {"n": 21})
        assert (await store.latest_snapshot("t-1", SnapshotKind.REPLAY)).sequence == 30

    async def test_deadlines(self, store):
        due = T0
        await store.write(LogWrite(deadline=Deadline("t-1", "orders", due)))
        await store.write(LogWrite(deadline=Deadline("t-2", "orders", due + timedelta(hours=1))))
        lease = timedelta(seconds=60)
        claimed = await store.claim_due_deadlines({"orders"}, due, lease)
        assert [d.transaction_id for d in claimed] == ["t-1"]
        assert await store.claim_due_deadlines({"orders"}, due, lease) == []  # leased
        assert await store.claim_due_deadlines({"payments"}, due + timedelta(days=1), lease) == []
        assert await store.claim_due_deadlines(set(), due, lease) == []
        retried = await store.claim_due_deadlines({"orders"}, due + timedelta(seconds=61), lease)
        assert [d.transaction_id for d in retried] == ["t-1"]
        await store.write(LogWrite(clear_deadlines=[("t-1", "orders")]))
        later = due + timedelta(days=1)
        assert [
            d.transaction_id for d in await store.claim_due_deadlines({"orders"}, later, lease)
        ] == ["t-2"]

    async def test_participants(self, store):
        await store.register_participant(Participant("inventory", region="us-east-1"))
        await store.register_participant(Participant("inventory", db_role="svc_inventory"))
        await store.register_participant(Participant("billing"))
        participants = await store.participants()
        assert [p.name for p in participants] == ["billing", "inventory"]
        assert (participants[1].db_role, participants[1].region) == ("svc_inventory", None)

    async def test_tenants_are_isolated(self, store):
        for tenant in ("acme", "globex"):
            with tenant_scope(tenant):
                await store.write(
                    LogWrite(transaction=tx(flow=tenant), events=[event()], activities=[activity()])
                )
                await store.register_participant(Participant(f"{tenant}-svc"))
        with tenant_scope("acme"):
            assert (await store.get_transaction("t-1")).flow == "acme"
            assert [e.tenant_id for e in await store.events("t-1")] == ["acme"]
            assert [a.tenant_id for a in await store.activities("t-1")] == ["acme"]
            assert [p.name for p in await store.participants()] == ["acme-svc"]
        assert await store.get_transaction("t-1") is None  # default tenant
        with system_scope():
            assert len(await store.list_transactions()) == 2
            assert len(await store.events("t-1")) == 2


class TestFactory:
    def test_urls(self, tmp_path):
        assert isinstance(create_saga_log_store("memory://"), InMemorySagaLogStore)
        assert create_saga_log_store(f"sqlite://{tmp_path}/l.db").db_path == f"{tmp_path}/l.db"
        assert create_saga_log_store("sqlite://").db_path == ":memory:"
        pg = create_saga_log_store("postgresql://u@h/db")
        assert type(pg).__name__ == "PostgreSQLSagaLogStore"
        with pytest.raises(ValueError, match="Unsupported"):
            create_saga_log_store("mongodb://x")

    async def test_context_manager(self):
        async with InMemorySagaLogStore() as store:
            assert await store.participants() == []
