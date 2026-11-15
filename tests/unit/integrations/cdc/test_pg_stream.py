"""ReplicationStream and AckState, driven synchronously (no thread)."""

from __future__ import annotations

import threading

import pytest

from sagaz.integrations.cdc._pg_stream import AckState, ReplicationStream, matches_table
from sagaz.integrations.cdc._pgoutput import PgOutputError, Relation
from tests.unit.integrations.cdc import pgoutput_encoder as enc
from tests.unit.integrations.cdc.fake_replication import (
    COMMITTED,
    OTHER_RELID,
    FakeReplicationCursor,
    FakeServer,
)


@pytest.fixture
def server():
    return FakeServer(slots={"s": 0})


@pytest.fixture
def cursor(server):
    cursor = FakeReplicationCursor(server)
    cursor.start_replication(slot_name="s")
    yield cursor
    cursor.close()


def make_stream(cursor, *, table="saga_outbox", accept=True):
    emitted = []

    def emit(changes):
        emitted.append(changes)
        return accept

    stream = ReplicationStream(
        cursor,
        table=table,
        emit=emit,
        acks=AckState(),
        stopping=threading.Event(),
        poll_interval=0.001,
    )
    return stream, emitted


def feed(stream, server, start=0):
    for txn in server.txns[start:]:
        for message in txn.messages:
            if not stream.handle(message):
                return False
    return True


class TestHandle:
    def test_groups_a_transaction(self, server, cursor):
        stream, emitted = make_stream(cursor)
        end = server.insert_outbox("a", "b", tenant_id="acme")
        assert feed(stream, server)
        assert len(emitted) == 1
        changes = emitted[0]
        assert [c.event.saga_id for c in changes] == ["a", "b"]
        assert {c.position for c in changes} == {end}
        assert {c.committed_at for c in changes} == {COMMITTED}
        assert all(c.event.tenant_id == "acme" for c in changes)
        assert stream.acks.delivered == end

    def test_other_tables_and_operations_are_ignored(self, server, cursor):
        stream, emitted = make_stream(cursor)
        server.commit(
            enc.outbox_values(saga_id="kept"),
            extra=[
                enc.insert(OTHER_RELID, ["7"]),
                enc.update(16384, enc.outbox_values(status="sent")),
                enc.delete(16384, ["x"]),
            ],
        )
        end = server.commit(["9"], relation_id=OTHER_RELID)
        feed(stream, server)
        assert [[c.event.saga_id for c in batch] for batch in emitted] == [["kept"]]
        assert stream.acks.idle == end

    def test_bad_rows_are_counted_and_skipped(self, server, cursor):
        stream, emitted = make_stream(cursor)
        server.commit(
            enc.outbox_values(saga_id="good"),
            enc.outbox_values(saga_id="bad-json", payload="{nope"),
            enc.outbox_values(saga_id="bad-status", status="weird"),
            enc.outbox_values(saga_id="", event_type=""),
        )
        end = server.commit(enc.outbox_values(saga_id="x", created_at="yesterday"))
        feed(stream, server)
        assert [[c.event.saga_id for c in batch] for batch in emitted] == [["good"]]
        assert stream.skipped_rows == 4
        assert stream.acks.idle == end

    def test_schema_qualified_table(self, server, cursor):
        stream, emitted = make_stream(cursor, table="tenant_a.saga_outbox")
        server.insert_outbox("public-row")
        feed(stream, server)
        assert emitted == []

    def test_emit_refusal_stops(self, server, cursor):
        stream, _ = make_stream(cursor, accept=False)
        server.insert_outbox("a")
        assert feed(stream, server) is False

    def test_insert_for_unknown_relation_fails(self, cursor):
        stream, _ = make_stream(cursor)
        with pytest.raises(PgOutputError):
            stream.handle(enc.insert(999, ["x"]))

    def test_commit_without_begin_uses_commit_time(self, server, cursor):
        stream, emitted = make_stream(cursor)
        stream.handle(enc.outbox_relation(16384))
        stream.handle(enc.insert(16384, enc.outbox_values()))
        stream.handle(enc.commit(0x10, 0x20, COMMITTED))
        assert emitted[0][0].committed_at == COMMITTED


class TestAckState:
    def test_target_follows_acks(self):
        acks = AckState()
        acks.deliver(100)
        assert acks.target() == 0
        acks.ack(100)
        assert acks.target() == 100
        acks.ack(50)  # never moves back
        assert acks.target() == 100

    def test_idle_transactions_after_everything_acked(self):
        acks = AckState()
        acks.deliver(100)
        acks.skip(150)
        assert acks.target() == 0  # 100 is still unacknowledged
        acks.ack(100)
        assert acks.target() == 150
        acks.deliver(200)
        assert acks.target() == 100
        acks.ack(200)
        assert acks.target() == 200


class TestRunAndFeedback:
    def test_run_streams_until_stopped_and_confirms_acks(self, server, cursor):
        stream, emitted = make_stream(cursor)
        end = server.insert_outbox("a")

        def emit(changes):
            emitted.append(changes)
            stream.acks.ack(changes[-1].position)
            stream.stopping.set()
            return True

        stream.emit = emit
        stream.run()
        assert len(emitted) == 1
        assert server.feedback == [end]
        assert server.slots["s"] == end

    def test_no_feedback_without_ack(self, server, cursor):
        stream, emitted = make_stream(cursor)
        server.insert_outbox("a")

        def emit(changes):
            emitted.append(changes)
            stream.stopping.set()
            return True

        stream.emit = emit
        stream.run()
        assert server.feedback == []

    def test_feedback_sent_once_per_advance(self, cursor, server):
        stream, _ = make_stream(cursor)
        stream.acks.ack(10)
        stream.send_feedback()
        stream.send_feedback()
        assert server.feedback == [10]


def test_matches_table():
    rel = Relation(1, "public", "saga_outbox", "d", ())
    assert matches_table(rel, "saga_outbox")
    assert matches_table(rel, "public.saga_outbox")
    assert not matches_table(rel, "other.saga_outbox")
    assert not matches_table(rel, "saga_outbox_archive")
