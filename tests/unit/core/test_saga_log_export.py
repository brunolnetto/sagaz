"""Ordered, durable reading of the saga log for exporters (ADR-013, #480).

``TestExportContract`` runs on the in-memory and SQLite stores here, and on
PostgreSQL in ``tests/integration/test_saga_log_postgresql.py``.
"""

from __future__ import annotations

import pytest

from sagaz.core.storage.saga_log import (
    ConcurrencyError,
    Coordination,
    InMemorySagaLogStore,
    LogWrite,
    SagaLogReader,
    SagaLogStore,
    StatusChange,
)
from sagaz.core.tenant import system_scope, tenant_scope
from tests.unit.core.test_saga_log import event, store, tx

__all__ = ["store"]  # the memory and SQLite fixture


async def write_flows(log) -> list[str]:
    """Two tenants, an orchestrated and a choreographed transaction; event ids in write order."""
    written = []
    with tenant_scope("acme"):
        stored = await log.write(
            LogWrite(transaction=tx("t-1"), events=[event("t-1"), event("t-1", "StepCompleted")])
        )
        written += [e.event_id for e in stored]
    with tenant_scope("globex"):
        stored = await log.write(
            LogWrite(
                transaction=tx("t-2", "order.created", Coordination.CHOREOGRAPHED),
                events=[event("t-2", "order.created")],
            )
        )
        written += [e.event_id for e in stored]
    with tenant_scope("acme"):
        stored = await log.write(LogWrite(events=[event("t-1", "SagaCompleted")]))
        written += [e.event_id for e in stored]
    return written


async def read_all(log, batch_size: int = 500) -> list:
    reader = SagaLogReader(log, "test", batch_size=batch_size)
    events = []
    while batch := await reader.read():
        events += batch.events
        await reader.acknowledge(batch)
    return events


class TestExportContract:
    async def test_every_tenant_in_write_order(self, store):
        written = await write_flows(store)
        exported = await read_all(store)
        assert [e.event.event_id for e in exported] == written
        assert [e.event.tenant_id for e in exported] == ["acme", "acme", "globex", "acme"]
        first, _, choreographed, _ = exported
        assert (first.coordination, first.flow) == ("orchestrated", "order")
        assert (choreographed.coordination, choreographed.flow) == (
            "choreographed",
            "order.created",
        )
        assert [e.event.sequence for e in exported] == [1, 2, 1, 3]

    async def test_batches_resume_after_their_position(self, store):
        written = await write_flows(store)
        assert [e.event.event_id for e in await read_all(store, batch_size=1)] == written

    async def test_an_exporter_resumes_from_its_cursor(self, store):
        await write_flows(store)
        first = SagaLogReader(store, "fluss", batch_size=3)
        await first.acknowledge(await first.read())
        unacknowledged = await first.read()  # read, never acknowledged: read again
        assert len(unacknowledged.events) == 1

        resumed = SagaLogReader(store, "fluss")
        rest = await resumed.read()
        assert [e.event.event_type for e in rest.events] == ["SagaCompleted"]
        assert len((await SagaLogReader(store, "other").read()).events) == 4

    async def test_a_caught_up_reader_keeps_its_position(self, store):
        await write_flows(store)
        reader = SagaLogReader(store, "fluss")
        batch = await reader.read()
        await reader.acknowledge(batch)
        empty = await reader.read()
        assert not empty
        assert empty.position == reader.position == batch.position
        await reader.acknowledge(empty)  # a no-op
        with system_scope():
            assert await store.load_cursor("fluss") == batch.position

    async def test_new_events_after_catching_up(self, store):
        await write_flows(store)
        reader = SagaLogReader(store, "fluss")
        await reader.acknowledge(await reader.read())
        with tenant_scope("globex"):
            await store.write(LogWrite(events=[event("t-2", "order.shipped")]))
        assert [e.event.event_type for e in (await reader.read()).events] == ["order.shipped"]

    async def test_a_rejected_write_exports_nothing(self, store):
        await store.write(LogWrite(transaction=tx("t-9"), events=[event("t-9")]))
        stale = StatusChange("t-9", "completed", expected_version=7)
        with pytest.raises(ConcurrencyError):
            await store.write(LogWrite(status=stale, events=[event("t-9", "SagaCompleted")]))
        assert [e.event.event_type for e in await read_all(store)] == ["SagaStarted"]


class TestInterface:
    async def test_stores_without_export_say_so(self):
        log = InMemorySagaLogStore()  # the base implementations, called directly
        with pytest.raises(NotImplementedError):
            await SagaLogStore.read_committed(log)
        with pytest.raises(NotImplementedError):
            await SagaLogStore.load_cursor(log, "x")
        with pytest.raises(NotImplementedError):
            await SagaLogStore.save_cursor(log, "x", "1")

    async def test_an_empty_log_has_no_position(self, store):
        reader = SagaLogReader(store, "fluss")
        batch = await reader.read()
        assert (batch.events, batch.position) == ([], None)
