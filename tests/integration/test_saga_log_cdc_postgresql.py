"""The saga log's CDC reader on PostgreSQL logical replication (#495).

Needs a server with ``wal_level=logical``: the ``logical_postgres_dsn`` fixture
(a container, or ``SAGAZ_CDC_PG_DSN``). Each test gets a database of its own and
a uniquely named reader, whose slot and publication are dropped afterwards.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from sagaz.core.storage.saga_log import (
    Coordination,
    EventKind,
    LogEvent,
    LogWrite,
    SagaLogExporter,
    Transaction,
)
from sagaz.core.tenant import tenant_scope

asyncpg = pytest.importorskip("asyncpg")
pytest.importorskip("psycopg2")

from sagaz.core.storage.saga_log.postgresql import PostgreSQLSagaLogStore  # noqa: E402
from sagaz.integrations.cdc.saga_log import SagaLogCDCReader  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="postgres")]


def _database(dsn: str, name: str) -> str:
    return urlunsplit(urlsplit(dsn)._replace(path=f"/{name}"))


@pytest.fixture
async def log_dsn(logical_postgres_dsn):
    name = f"sagaz_logcdc_{uuid4().hex[:8]}"
    admin = await asyncpg.connect(logical_postgres_dsn)
    try:
        await admin.execute(f"CREATE DATABASE {name}")
    finally:
        await admin.close()
    dsn = _database(logical_postgres_dsn, name)
    yield dsn
    admin = await asyncpg.connect(logical_postgres_dsn)
    try:
        await admin.execute(
            "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots"
            " WHERE database = $1",
            name,
        )
        await admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
    finally:
        await admin.close()


@pytest.fixture
async def log(log_dsn):
    store = PostgreSQLSagaLogStore(log_dsn)
    yield store
    await store.close()


def reader(log, dsn: str, name: str) -> SagaLogCDCReader:
    cdc = SagaLogCDCReader(log, dsn, name=name, idle_timeout=0.3)
    cdc.source.max_batch_delay = 0.05
    cdc.source.poll_interval = 0.02
    return cdc


async def write_flow(log, tid: str, events: int = 2, tenant: str = "acme") -> None:
    with tenant_scope(tenant):
        await log.write(
            LogWrite(
                transaction=Transaction(tid, "order", Coordination.ORCHESTRATED),
                events=[LogEvent(tid, f"Step{i}", EventKind.LIFECYCLE) for i in range(events)],
            )
        )


async def read_until(cdc: SagaLogCDCReader, count: int, timeout: float = 30) -> list:
    events: list = []
    batches = []
    deadline = asyncio.get_running_loop().time() + timeout
    while len(events) < count and asyncio.get_running_loop().time() < deadline:
        batch = await cdc.read()
        if batch.events:
            events += batch.events
            batches.append(batch)
    assert len(events) >= count, f"read {len(events)} of {count}"
    return batches


async def test_committed_events_stream_in_commit_order(log, log_dsn):
    name = f"it{uuid4().hex[:8]}"
    cdc = reader(log, log_dsn, name)
    try:
        await cdc.read()  # starts streaming (creates the slot): later commits are captured
        await write_flow(log, "t-1")
        await write_flow(log, "t-2", tenant="globex")
        batches = await read_until(cdc, 4)
        events = [e for b in batches for e in b.events]
        assert [(e.event.tenant_id, e.event.transaction_id, e.event.sequence) for e in events] == [
            ("acme", "t-1", 1),
            ("acme", "t-1", 2),
            ("globex", "t-2", 1),
            ("globex", "t-2", 2),
        ]
        assert {(e.coordination, e.flow) for e in events} == {("orchestrated", "order")}
        positions = [int(b.position) for b in batches]
        assert positions == sorted(positions)
        for batch in batches:
            await cdc.acknowledge(batch)
    finally:
        await cdc.close()


async def test_unacknowledged_changes_are_read_again(log, log_dsn):
    name = f"it{uuid4().hex[:8]}"
    first = reader(log, log_dsn, name)
    await first.read()  # create the slot
    await write_flow(log, "t-1")
    batches = await read_until(first, 2)
    await first.close()  # never acknowledged

    second = reader(log, log_dsn, name)
    try:
        again = await read_until(second, 2)
        assert [e.event.event_id for b in again for e in b.events] == [
            e.event.event_id for b in batches for e in b.events
        ]
        for batch in again:
            await second.acknowledge(batch)
    finally:
        await second.close()

    third = reader(log, log_dsn, name)
    try:
        assert not (await third.read()).events  # acknowledged: not read again
        await write_flow(log, "t-3", events=1)
        (batch,) = await read_until(third, 1)
        assert batch.events[0].event.transaction_id == "t-3"
    finally:
        await third.close()


async def test_the_exporter_moves_concurrent_writes_once(log, log_dsn):
    name = f"it{uuid4().hex[:8]}"
    received: list = []

    class Sink:
        async def write(self, events):
            received.extend(events)

        async def close(self):
            pass

    cdc = reader(log, log_dsn, name)
    await cdc.read()
    other = PostgreSQLSagaLogStore(log_dsn)
    try:
        await asyncio.gather(
            *(write_flow(log if i % 2 else other, f"t-{i}", events=1) for i in range(30))
        )
        exporter = SagaLogExporter(cdc, Sink(), poll_interval=0.01)
        deadline = asyncio.get_running_loop().time() + 30
        while len(received) < 30 and asyncio.get_running_loop().time() < deadline:
            await exporter.export()
        await exporter.close()
    finally:
        await other.close()
    assert sorted(e.event.transaction_id for e in received) == sorted(f"t-{i}" for i in range(30))
