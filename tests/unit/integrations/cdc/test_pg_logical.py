"""PgLogicalSource with a fake psycopg2 server: thread hand-off, batching, acks."""

from __future__ import annotations

import asyncio

import pytest

from sagaz.integrations.cdc import CDCError, CDCSource
from sagaz.integrations.cdc.pg_logical import PgLogicalSource
from tests.unit.integrations.cdc import pgoutput_encoder as enc
from tests.unit.integrations.cdc.fake_replication import FakeServer

pytestmark = pytest.mark.timeout(30)


@pytest.fixture
def server():
    return FakeServer()


def make_source(server, **kwargs):
    options = {
        "poll_interval": 0.005,
        "max_batch_delay": 0.02,
        "connection_factory": server.connect,
    }
    options.update(kwargs)
    return PgLogicalSource("postgresql://fake", **options)


async def next_batch(iterator, timeout=5.0):
    return await asyncio.wait_for(anext(iterator), timeout)


async def collect(iterator, count, timeout=5.0):
    """Changes from successive batches until ``count`` have arrived."""
    changes = []
    while len(changes) < count:
        changes += await next_batch(iterator, timeout)
    return changes


async def until(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class TestLifecycle:
    async def test_is_a_cdc_source(self, server):
        source = make_source(server)
        assert isinstance(source, CDCSource)
        assert source.name == "pg_logical"
        assert source.skipped_rows == 0
        assert not source.running

    async def test_start_creates_publication_and_slot_once(self, server):
        source = make_source(server)
        await source.start()
        assert server.publications == {"sagaz_outbox_pub"}
        assert set(server.slots) == {"sagaz_outbox"}
        assert any("FOR TABLE saga_outbox" in sql for sql in server.statements)
        await source.stop()

        created = len([s for s in server.statements if s.startswith(("CREATE", "SELECT pg_c"))])
        again = make_source(server)
        await again.start()
        await again.stop()
        assert len([s for s in server.statements if s.startswith(("CREATE", "SELECT pg_c"))]) == (
            created
        )
        assert server.open_connections == 0

    async def test_start_replication_options(self, server):
        source = make_source(server, slot="mine", publication="pub", feedback_interval=3.0)
        await source.start()
        cursor_kwargs = None
        await until(lambda: source.running)
        cursor_kwargs = source._stream.cursor.started
        await source.stop()
        assert cursor_kwargs == {
            "slot_name": "mine",
            "decode": False,
            "options": {"proto_version": "1", "publication_names": "pub"},
            "status_interval": 3.0,
        }

    async def test_create_false_uses_existing_objects(self, server):
        server.slots["sagaz_outbox"] = 0
        source = make_source(server, create=False)
        await source.start()
        await source.stop()
        assert server.statements == []

    async def test_create_false_without_slot_fails(self, server):
        source = make_source(server, create=False)
        with pytest.raises(CDCError, match="cannot start replication"):
            await source.start()
        assert server.open_connections == 0

    async def test_setup_failure(self, server):
        server.create_error = RuntimeError("permission denied for database")
        with pytest.raises(CDCError, match="cannot create publication"):
            await make_source(server).start()
        assert server.open_connections == 0

    async def test_connection_failure(self, server):
        server.connect_error = OSError("connection refused")
        with pytest.raises(CDCError, match="connection refused"):
            await make_source(server).start()

    async def test_start_twice_and_stop_twice(self, server):
        source = make_source(server)
        await source.start()
        with pytest.raises(CDCError, match="already started"):
            await source.start()
        await source.stop()
        await source.stop()
        assert not source.running

    async def test_changes_before_start(self, server):
        with pytest.raises(CDCError, match="before start"):
            await anext(make_source(server).changes())

    async def test_stop_ends_iteration(self, server):
        source = make_source(server)
        await source.start()
        iterator = source.changes()
        pending = asyncio.ensure_future(anext(iterator))
        await asyncio.sleep(0.02)
        await source.stop()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, 5)
        # A finished source keeps reporting the end.
        with pytest.raises(StopAsyncIteration):
            await anext(source.changes())

    async def test_drop_slot(self, server):
        source = make_source(server)
        await source.start()
        with pytest.raises(CDCError, match="stop the source"):
            await source.drop_slot()
        await source.stop()
        assert await source.drop_slot() is True
        assert server.slots == {}
        assert server.publications == {"sagaz_outbox_pub"}
        assert await source.drop_slot(drop_publication=True) is False
        assert server.publications == set()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"slot": "Bad-Slot"},
            {"publication": "pub; DROP TABLE x"},
            {"table": "a.b.c"},
            {"table": "1table"},
            {"batch_size": 0},
            {"queue_size": 0},
        ],
    )
    def test_invalid_arguments(self, server, kwargs):
        with pytest.raises(ValueError):
            make_source(server, **kwargs)


class TestDelivery:
    async def test_changes_carry_event_commit_time_and_position(self, server):
        source = make_source(server)
        await source.start()
        end = server.insert_outbox("a", "b", tenant_id="acme")
        batch = await next_batch(source.changes())
        await source.stop()
        assert [c.event.saga_id for c in batch] == ["a", "b"]
        assert {c.position for c in batch} == {end}
        assert all(c.event.tenant_id == "acme" for c in batch)
        assert all(c.committed_at == batch[0].committed_at for c in batch)

    async def test_batches_group_transactions_until_the_delay(self, server):
        source = make_source(server, max_batch_delay=0.3)
        await source.start()
        iterator = source.changes()
        for name in ("a", "b", "c"):
            server.insert_outbox(name)
        batch = await next_batch(iterator)
        await source.stop()
        assert [c.event.saga_id for c in batch] == ["a", "b", "c"]
        assert [c.position for c in batch] == sorted(c.position for c in batch)

    async def test_batch_size_never_splits_a_transaction(self, server):
        source = make_source(server, batch_size=3, max_batch_delay=0.5)
        server.slots["sagaz_outbox"] = 0
        server.publications.add("sagaz_outbox_pub")
        server.insert_outbox("t1-a", "t1-b")
        server.insert_outbox("t2-a", "t2-b")
        server.insert_outbox("t3-a")
        await source.start()
        iterator = source.changes()
        first = await next_batch(iterator)
        second = await next_batch(iterator)
        await source.stop()
        assert [c.event.saga_id for c in first] == ["t1-a", "t1-b", "t2-a", "t2-b"]
        assert [c.event.saga_id for c in second] == ["t3-a"]

    async def test_backpressure_keeps_order(self, server):
        source = make_source(server, queue_size=1, batch_size=1, max_batch_delay=0)
        await source.start()
        for i in range(20):
            server.insert_outbox(f"s{i}")
        iterator = source.changes()
        changes = []
        for _ in range(20):
            changes += await next_batch(iterator)
            await asyncio.sleep(0.001)
        await source.stop()
        assert [c.event.saga_id for c in changes] == [f"s{i}" for i in range(20)]

    async def test_stop_while_the_queue_is_full(self, server):
        source = make_source(server, queue_size=1)
        await source.start()
        for i in range(5):
            server.insert_outbox(f"s{i}")
        await asyncio.sleep(0.1)
        await source.stop()
        assert not source.running
        assert server.open_connections == 0

    async def test_bad_rows_are_skipped_and_acked_past(self, server):
        source = make_source(server)
        await source.start()
        server.commit(enc.outbox_values(saga_id="bad", payload="{nope"))
        end = server.insert_outbox("good")
        changes = await collect(source.changes(), 1)
        assert [c.event.saga_id for c in changes] == ["good"]
        assert source.skipped_rows == 1
        await source.ack(end)
        await until(lambda: server.slots["sagaz_outbox"] == end)
        await source.stop()


class TestAcknowledgement:
    async def test_feedback_only_after_ack(self, server):
        source = make_source(server)
        await source.start()
        first = server.insert_outbox("a")
        second = server.insert_outbox("b")
        await collect(source.changes(), 2)
        await asyncio.sleep(0.05)
        assert server.feedback == []
        await source.ack(first)
        await until(lambda: server.feedback == [first])
        await source.ack(None)
        await source.ack(second)
        await until(lambda: server.feedback == [first, second])
        await source.stop()

    async def test_restart_redelivers_unacknowledged_changes(self, server):
        source = make_source(server)
        await source.start()
        first = server.insert_outbox("a")
        server.insert_outbox("b")
        await collect(source.changes(), 2)
        await source.ack(first)
        await source.stop()  # stopping confirms what was acknowledged

        again = make_source(server)
        await again.start()
        changes = await collect(again.changes(), 1)
        assert [c.event.saga_id for c in changes] == ["b"]
        await again.ack(changes[-1].position)
        await again.stop()

        last = make_source(server, max_batch_delay=0.05)
        await last.start()
        server.insert_outbox("c")
        changes = await collect(last.changes(), 1)
        await last.stop()
        assert [c.event.saga_id for c in changes] == ["c"]

    async def test_quiet_transactions_are_confirmed_once_caught_up(self, server):
        source = make_source(server)
        await source.start()
        delivered = server.insert_outbox("a")
        await collect(source.changes(), 1)
        idle = server.commit(["1"], relation_id=16400)
        await asyncio.sleep(0.05)
        assert server.feedback == []
        await source.ack(delivered)
        await until(lambda: server.slots["sagaz_outbox"] == idle)
        await source.stop()


class TestErrors:
    async def test_reader_error_surfaces_from_changes(self, server):
        source = make_source(server)
        await source.start()
        server.read_error = RuntimeError("server closed the connection")
        with pytest.raises(CDCError, match="server closed the connection") as info:
            await next_batch(source.changes())
        assert isinstance(info.value.__cause__, RuntimeError)
        await until(lambda: not source.running)
        await source.stop()
        assert server.open_connections == 0

    async def test_error_after_a_batch_is_delivered_next(self, server):
        source = make_source(server, max_batch_delay=0.5)
        await source.start()
        iterator = source.changes()
        server.insert_outbox("a")
        await until(lambda: source._queue.qsize() > 0)
        server.read_error = RuntimeError("boom")
        batch = await next_batch(iterator)
        assert [c.event.saga_id for c in batch] == ["a"]
        with pytest.raises(CDCError, match="boom"):
            await next_batch(iterator)
        await source.stop()
