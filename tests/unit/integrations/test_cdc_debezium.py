"""DebeziumKafkaSource and Debezium envelope decoding (ADR-011, #50), without Kafka."""

from __future__ import annotations

import json
import logging
from collections import namedtuple
from datetime import UTC, datetime
from typing import Any

import pytest

from sagaz.core.outbox.types import OutboxStatus
from sagaz.integrations.cdc import CDCError, CDCSource
from sagaz.integrations.cdc._debezium_envelope import commit_time, decode_value, unwrap
from sagaz.integrations.cdc.debezium import (
    DEFAULT_GROUP_ID,
    DebeziumKafkaSource,
    _aiokafka_consumer,
    outbox_topic,
)

TP = namedtuple("TP", "topic partition")
Record = namedtuple("Record", "offset value")

TOPIC = "sagaz.public.saga_outbox"
P0 = TP(TOPIC, 0)
P1 = TP(TOPIC, 1)
COMMIT_MS = 1_763_160_054_123  # 2025-11-14T22:40:54.123Z


def row(**overrides: Any) -> dict[str, Any]:
    """A saga_outbox row as Debezium's JsonConverter writes it."""
    values = {
        "event_id": "6f1c1c1e-6a39-4bfa-9d7c-1b7a0f1f2a10",
        "saga_id": "order-1",
        "aggregate_type": "order",
        "aggregate_id": "ORD-1",
        "event_type": "OrderCreated",
        "payload": '{"amount": 10.5, "items": [1, 2]}',  # jsonb: io.debezium.data.Json
        "headers": '{"trace_id": "t-1"}',
        "status": "pending",
        "created_at": "2025-11-14T22:40:54.000123Z",  # timestamptz: ZonedTimestamp
        "claimed_at": None,
        "retry_count": 0,
        "replay_count": 0,
        "routing_key": "orders",
        "partition_key": "ORD-1",
        "tenant_id": "acme",
    }
    values.update(overrides)
    return values


def envelope(op: str = "c", after: Any = None, *, source_ts: Any = COMMIT_MS, **extra: Any):
    document = {
        "before": None,
        "after": row() if after is None else after,
        "source": {"connector": "postgresql", "table": "saga_outbox", "ts_ms": source_ts},
        "op": op,
        "ts_ms": COMMIT_MS + 50,
    }
    document.update(extra)
    return document


def encoded(document: Any) -> bytes:
    return json.dumps(document).encode()


# ---------------------------------------------------------------------------
# Envelope decoding
# ---------------------------------------------------------------------------


class TestDecodeValue:
    def test_insert_without_schema(self):
        event, committed_at = decode_value(encoded(envelope()))
        assert event.event_id == "6f1c1c1e-6a39-4bfa-9d7c-1b7a0f1f2a10"
        assert event.payload == {"amount": 10.5, "items": [1, 2]}
        assert event.headers == {"trace_id": "t-1"}
        assert event.tenant_id == "acme"
        assert event.status is OutboxStatus.PENDING
        assert event.routing_key == "orders"
        assert event.created_at == datetime(2025, 11, 14, 22, 40, 54, 123, tzinfo=UTC)
        assert committed_at == datetime(2025, 11, 14, 22, 40, 54, 123000, tzinfo=UTC)

    def test_insert_with_schema_wrapper(self):
        wrapped = {"schema": {"type": "struct", "fields": []}, "payload": envelope()}
        event, _ = decode_value(encoded(wrapped))
        assert event.saga_id == "order-1"

    def test_schema_wrapper_with_null_payload_is_skipped(self):
        assert decode_value(encoded({"schema": None, "payload": None})) is None

    def test_string_value_accepted(self):
        event, _ = decode_value(json.dumps(envelope()))
        assert event.event_type == "OrderCreated"

    def test_tombstone_is_skipped(self):
        assert decode_value(None) is None

    @pytest.mark.parametrize("op", ["u", "d", "t", "m"])
    def test_other_ops_are_skipped(self, op):
        assert decode_value(encoded(envelope(op))) is None

    def test_snapshot_read_of_pending_row(self):
        event, _ = decode_value(encoded(envelope("r")))
        assert event.status is OutboxStatus.PENDING

    def test_snapshot_read_of_row_without_status(self):
        after = row()
        del after["status"]
        assert decode_value(encoded(envelope("r", after))) is not None

    @pytest.mark.parametrize("status", ["sent", "claimed", "dead_letter"])
    def test_snapshot_read_of_published_row_is_skipped(self, status):
        assert decode_value(encoded(envelope("r", row(status=status)))) is None

    def test_native_json_columns(self):
        after = row(payload={"a": 1}, headers=None, created_at=1_763_160_054_000_123)
        event, _ = decode_value(encoded(envelope(after=after)))
        assert event.payload == {"a": 1}
        assert event.headers == {}
        assert event.created_at == datetime(2025, 11, 14, 22, 40, 54, 123, tzinfo=UTC)

    @pytest.mark.parametrize(
        "value",
        [
            b"\xff\xfe not utf8",
            b"{not json",
            b"[1, 2]",
            encoded({"op": "x", "after": row()}),
            encoded({"before": None, "after": row()}),
            encoded(envelope(after="not a row")),
            encoded(envelope(after=row(event_id=None))),
            encoded(envelope(after=row(payload="{bad"))),
            encoded(envelope(after=row(status="bogus"))),
            encoded(envelope(after=row(retry_count="many"))),
            encoded(envelope(source_ts="yesterday")),
        ],
    )
    def test_undecodable_values_raise(self, value):
        with pytest.raises(CDCError):
            decode_value(value)


class TestEnvelopeHelpers:
    def test_unwrap_leaves_bare_envelope(self):
        bare = envelope()
        assert unwrap(bare) is bare

    def test_unwrap_does_not_take_row_payload(self):
        # A bare envelope always has "op"; a wrapper never does.
        document = {"schema": 1, "payload": 2, "op": "c"}
        assert unwrap(document) is document

    def test_commit_time_falls_back_to_envelope_ts(self):
        document = envelope(source_ts=None)
        assert commit_time(document) == datetime(2025, 11, 14, 22, 40, 54, 173000, tzinfo=UTC)

    def test_commit_time_without_source(self):
        document = {"op": "c", "ts_ms": COMMIT_MS}
        assert commit_time(document) is not None

    def test_commit_time_absent(self):
        assert commit_time({"op": "c", "source": {"ts_ms": 0}}) is None


# ---------------------------------------------------------------------------
# DebeziumKafkaSource with a fake consumer
# ---------------------------------------------------------------------------


class FakeConsumer:
    """Plays back scripted ``getmany`` results and records commits."""

    def __init__(self, source_ref: list, polls: list, *, fail_start=False, fail_commit=False):
        self.source_ref = source_ref
        self.polls = list(polls)
        self.commits: list[dict] = []
        self.started = self.stopped = False
        self.fail_start = fail_start
        self.fail_commit = fail_commit
        self.poll_args: list[dict] = []

    async def start(self):
        if self.fail_start:
            msg = "broker down"
            raise ConnectionError(msg)
        self.started = True

    async def stop(self):
        self.stopped = True

    async def getmany(self, **kwargs):
        self.poll_args.append(kwargs)
        if not self.polls:
            await self.source_ref[0].stop()  # script exhausted: end the stream
            return {}
        result = self.polls.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def commit(self, offsets):
        if self.fail_commit:
            msg = "rebalanced"
            raise RuntimeError(msg)
        self.commits.append(dict(offsets))


def make_source(polls, **kwargs):
    ref: list = []
    created: dict[str, Any] = {}
    options = {k: kwargs.pop(k) for k in ("fail_start", "fail_commit") if k in kwargs}

    def factory(topic, **config):
        created["topic"] = topic
        created["config"] = config
        created["consumer"] = FakeConsumer(ref, polls, **options)
        return created["consumer"]

    source = DebeziumKafkaSource("kafka:9092", consumer_factory=factory, **kwargs)
    ref.append(source)
    return source, created


async def collect(source, *, ack=True):
    batches = []
    async for batch in source.changes():
        batches.append(batch)
        if ack:
            await source.ack(batch[-1].position)
    return batches


def rec(offset, document=None, *, raw=None):
    if raw is not None or document is None:
        return Record(offset, raw)
    return Record(offset, encoded(document))


def ins(event_id, **after):
    return envelope(after=row(event_id=event_id, **after))


@pytest.mark.asyncio
class TestDebeziumKafkaSource:
    async def test_satisfies_protocol_and_defaults(self):
        source, created = make_source([])
        assert isinstance(source, CDCSource)
        assert source.name == "debezium"
        assert source.topic == TOPIC == outbox_topic()
        await source.start()
        assert created["topic"] == TOPIC
        config = created["config"]
        assert config["enable_auto_commit"] is False
        assert config["group_id"] == DEFAULT_GROUP_ID
        assert config["auto_offset_reset"] == "earliest"
        assert config["bootstrap_servers"] == "kafka:9092"
        assert source.consumer_config == config
        await source.stop()
        assert created["consumer"].stopped

    async def test_options_and_topic(self):
        source, created = make_source(
            [],
            topic_prefix="prod",
            group_id="g",
            consumer_options={"security_protocol": "SASL_SSL", "enable_auto_commit": True},
        )
        assert source.topic == "prod.public.saga_outbox"
        await source.start()
        assert created["config"]["security_protocol"] == "SASL_SSL"
        assert created["config"]["enable_auto_commit"] is False
        assert created["config"]["group_id"] == "g"
        explicit, _ = make_source([], topic="custom")
        assert explicit.topic == "custom"

    @pytest.mark.parametrize(("size", "wait"), [(0, 10), (10, -1)])
    async def test_invalid_batching(self, size, wait):
        with pytest.raises(ValueError):
            DebeziumKafkaSource(max_batch_size=size, max_wait_ms=wait)

    async def test_start_is_idempotent(self):
        source, created = make_source([])
        await source.start()
        consumer = created["consumer"]
        await source.start()
        assert created["consumer"] is consumer

    async def test_start_failure(self):
        source, _ = make_source([], fail_start=True)
        with pytest.raises(CDCError, match="broker down"):
            await source.start()
        with pytest.raises(CDCError, match="not started"):
            await source.ack({P0: 1})

    async def test_changes_require_start(self):
        source, _ = make_source([])
        with pytest.raises(CDCError, match="not started"):
            await anext(source.changes())

    async def test_stop_without_start(self):
        source, _ = make_source([])
        await source.stop()

    async def test_batches_and_offset_commit(self):
        polls = [
            {P0: [rec(0, ins("a")), rec(1, ins("b"))]},
            {},
            {P0: [rec(2, ins("c"))]},
        ]
        source, created = make_source(polls, max_batch_size=2, max_wait_ms=25)
        await source.start()
        batches = await collect(source)
        assert [[c.event.event_id for c in b] for b in batches] == [["a", "b"], ["c"]]
        assert batches[0][0].position == {P0: 0}
        assert batches[0][1].position == {P0: 1}
        assert batches[0][0].committed_at == datetime(2025, 11, 14, 22, 40, 54, 123000, tzinfo=UTC)
        consumer = created["consumer"]
        assert consumer.commits == [{P0: 2}, {P0: 3}]
        assert consumer.poll_args[0] == {"timeout_ms": 25, "max_records": 2}

    async def test_unacked_batch_is_not_committed(self):
        source, created = make_source([{P0: [rec(0, ins("a"))]}])
        await source.start()
        batches = await collect(source, ack=False)
        assert len(batches) == 1
        assert created["consumer"].commits == []

    async def test_skipped_and_bad_records_do_not_stop_the_stream(self, caplog):
        polls = [
            {
                P0: [
                    rec(0, ins("a")),
                    rec(1),  # tombstone
                    rec(2, raw=b"{garbage"),
                    rec(3, envelope("u")),
                    rec(4, ins("b")),
                    rec(5, envelope("d")),
                ]
            }
        ]
        source, created = make_source(polls)
        await source.start()
        with caplog.at_level(logging.WARNING):
            batches = await collect(source)
        assert [c.event.event_id for c in batches[0]] == ["a", "b"]
        assert batches[0][0].position == {P0: 0}
        # The last change's position covers the trailing skipped record too.
        assert batches[0][-1].position == {P0: 5}
        assert created["consumer"].commits == [{P0: 6}]
        assert source.stats.received == 6
        assert source.stats.changes == 2
        assert source.stats.skipped == 3
        assert source.stats.failed == 1
        assert "undecodable" in caplog.text

    async def test_batch_of_only_skipped_records_is_committed(self):
        polls = [{P0: [rec(0), rec(1, raw=b"nope")]}]
        source, created = make_source(polls)
        await source.start()
        assert await collect(source) == []
        assert created["consumer"].commits == [{P0: 2}]

    async def test_skipped_records_wait_for_outstanding_ack(self):
        polls = [{P0: [rec(0, ins("a"))]}, {P0: [rec(1, envelope("u"))]}, {P0: [rec(2, ins("b"))]}]
        source, created = make_source(polls)
        await source.start()
        consumer = None
        batches = []
        async for batch in source.changes():
            batches.append(batch)
            consumer = created["consumer"]
            if len(batches) == 2:
                # Batch 1 was not acknowledged, so the skipped record was not committed.
                assert consumer.commits == []
                assert batch[-1].position == {P0: 2}
                await source.ack(batches[0][-1].position)
                await source.ack(batch[-1].position)
        assert consumer.commits == [{P0: 1}, {P0: 3}]

    async def test_multiple_partitions(self):
        polls = [{P0: [rec(7, ins("a"))], P1: [rec(3, ins("b")), rec(4, envelope("d"))]}]
        source, created = make_source(polls)
        await source.start()
        batches = await collect(source)
        assert batches[0][0].position == {P0: 7}
        assert batches[0][1].position == {P0: 7, P1: 4}
        assert created["consumer"].commits == [{P0: 8, P1: 5}]

    async def test_ack_of_empty_position_is_a_noop(self):
        source, created = make_source([])
        await source.start()
        await source.ack(None)
        await source.ack({})
        assert created["consumer"].commits == []

    async def test_commit_failure(self):
        source, _ = make_source([], fail_commit=True)
        await source.start()
        with pytest.raises(CDCError, match="rebalanced"):
            await source.ack({P0: 3})

    async def test_poll_failure(self):
        source, _ = make_source([RuntimeError("fetch failed")])
        await source.start()
        with pytest.raises(CDCError, match="fetch failed"):
            await collect(source)

    async def test_poll_failure_after_stop_ends_the_stream(self):
        source, _ = make_source([])

        class Closing(FakeConsumer):
            async def getmany(self, **kwargs):
                await source.stop()
                msg = "consumer closed"
                raise RuntimeError(msg)

        source._factory = lambda topic, **config: Closing([source], [])
        await source.start()
        assert await collect(source) == []

    async def test_restart_resets_tracking(self):
        source, _ = make_source([{P0: [rec(0, ins("a"))]}])
        await source.start()
        await collect(source, ack=False)
        await source.start()
        assert source._outstanding is None
        assert source._seen == {}


@pytest.mark.asyncio
async def test_default_factory_builds_aiokafka_consumer():
    aiokafka = pytest.importorskip("aiokafka")
    consumer = _aiokafka_consumer(TOPIC, bootstrap_servers="localhost:1", enable_auto_commit=False)
    assert isinstance(consumer, aiokafka.AIOKafkaConsumer)
