"""The RabbitMQ and Redis Streams buses encode events through a serializer (#566).

As the Kafka bus does: with ``serializer=`` (for example
``SchemaRegistrySerializer(envelope="choreography")``), the whole event
(``event.to_dict()``) is encoded. Without one, the format is unchanged. The trace context
survives either way (#563). A fake serializer stands in for the registry.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sagaz.choreography.events import Event

TRACEPARENT = {"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"}


class FakeSerializer:
    """Encodes the envelope as tagged JSON and records what it was asked."""

    def __init__(self) -> None:
        self.serialized: list[tuple[str, dict[str, Any], str]] = []
        self.deserialized: list[str] = []

    async def serialize(self, topic: str, envelope: dict[str, Any], event_type: str) -> bytes:
        self.serialized.append((topic, envelope, event_type))
        return b"FAKE" + json.dumps(envelope).encode()

    async def deserialize(self, topic: str, value: bytes) -> dict[str, Any]:
        self.deserialized.append(topic)
        assert value.startswith(b"FAKE")
        loaded: dict[str, Any] = json.loads(value[4:])
        return loaded


def event() -> Event:
    return Event(
        "order.created",
        {"order_id": "o-1"},
        saga_id="t-1",
        tenant_id="acme",
        source="orders",
        trace_context=TRACEPARENT,
        lineage=(("e-0", "checkout"), ("e-1", None)),
    )


def same(received: Event, sent: Event) -> None:
    assert received.event_id == sent.event_id
    assert received.data == sent.data
    assert received.saga_id == sent.saga_id
    assert received.tenant_id == sent.tenant_id
    assert received.trace_context == sent.trace_context
    assert received.lineage == sent.lineage


class TestRabbitMQ:
    @staticmethod
    def bus(serializer: Any = None) -> Any:
        pytest.importorskip("aio_pika")
        from sagaz.choreography.buses.rabbitmq import RabbitMQEventBus, RabbitMQEventBusConfig

        bus = RabbitMQEventBus(RabbitMQEventBusConfig(exchange_name="ex", serializer=serializer))
        bus._exchange = AsyncMock()
        return bus

    @staticmethod
    async def sent_message(bus: Any, sent: Event) -> Any:
        await bus.publish(sent)
        message = bus._exchange.publish.call_args.args[0]
        incoming = MagicMock()
        incoming.body = message.body
        incoming.content_type = message.content_type
        incoming.process.return_value.__aenter__ = AsyncMock(return_value=None)
        incoming.process.return_value.__aexit__ = AsyncMock(return_value=None)
        return incoming

    @staticmethod
    async def received(bus: Any, incoming: Any) -> list[Event]:
        got: list[Event] = []

        async def handler(e: Event) -> None:
            got.append(e)

        bus.subscribe("order.created", handler)
        await bus._on_message(incoming)
        return got

    async def test_with_a_serializer_the_body_is_the_encoded_envelope(self):
        serializer = FakeSerializer()
        bus = self.bus(serializer)
        sent = event()
        incoming = await self.sent_message(bus, sent)
        assert incoming.body.startswith(b"FAKE")
        assert incoming.content_type == "application/octet-stream"
        topic, envelope, event_type = serializer.serialized[0]
        assert (topic, event_type) == ("ex", "order.created")
        assert envelope == sent.to_dict()  # the whole event, trace context included
        [got] = await self.received(bus, incoming)
        same(got, sent)
        assert serializer.deserialized == ["ex"]

    async def test_without_a_serializer_the_body_stays_json(self):
        bus = self.bus()
        sent = event()
        incoming = await self.sent_message(bus, sent)
        assert incoming.content_type == "application/json"
        assert json.loads(incoming.body)["event_id"] == sent.event_id
        [got] = await self.received(bus, incoming)
        same(got, sent)

    async def test_a_bus_with_a_serializer_still_reads_json_messages(self):
        sent = event()
        incoming = await self.sent_message(self.bus(), sent)  # published before switching
        serializer = FakeSerializer()
        [got] = await self.received(self.bus(serializer), incoming)
        same(got, sent)
        assert serializer.deserialized == []


class TestRedisStreams:
    @staticmethod
    def bus(serializer: Any = None) -> Any:
        from sagaz.choreography.buses.redis_streams import (
            RedisStreamsBusConfig,
            RedisStreamsEventBus,
        )

        bus = RedisStreamsEventBus(RedisStreamsBusConfig(stream_name="st", serializer=serializer))
        bus._client = AsyncMock()
        return bus

    @staticmethod
    async def sent_fields(bus: Any, sent: Event) -> dict[bytes, bytes]:
        await bus.publish(sent)
        _, fields = bus._client.xadd.call_args.args
        return {k.encode(): v if isinstance(v, bytes) else v.encode() for k, v in fields.items()}

    @staticmethod
    async def received(bus: Any, fields: dict[bytes, bytes]) -> list[Event]:
        got: list[Event] = []

        async def handler(e: Event) -> None:
            got.append(e)

        bus.subscribe("order.created", handler)
        await bus._dispatch(fields)
        return got

    async def test_with_a_serializer_one_field_holds_the_envelope(self):
        pytest.importorskip("redis")
        serializer = FakeSerializer()
        bus = self.bus(serializer)
        sent = event()
        fields = await self.sent_fields(bus, sent)
        assert set(fields) == {b"envelope", b"event_type", b"saga_id"}
        assert fields[b"envelope"].startswith(b"FAKE")
        assert (fields[b"event_type"], fields[b"saga_id"]) == (b"order.created", b"t-1")
        topic, envelope, _ = serializer.serialized[0]
        assert topic == "st"
        assert envelope == sent.to_dict()
        [got] = await self.received(bus, fields)
        same(got, sent)

    async def test_without_a_serializer_the_fields_are_unchanged(self):
        pytest.importorskip("redis")
        bus = self.bus()
        sent = event()
        fields = await self.sent_fields(bus, sent)
        assert b"envelope" not in fields
        assert json.loads(fields[b"data"]) == {"order_id": "o-1"}
        [got] = await self.received(bus, fields)
        same(got, sent)

    async def test_a_bus_with_a_serializer_still_reads_field_entries(self):
        pytest.importorskip("redis")
        sent = event()
        fields = await self.sent_fields(self.bus(), sent)  # written before switching
        [got] = await self.received(self.bus(FakeSerializer()), fields)
        same(got, sent)

    async def test_an_envelope_without_a_serializer_is_skipped_and_logged(self, caplog):
        pytest.importorskip("redis")
        fields = await self.sent_fields(self.bus(FakeSerializer()), event())
        with caplog.at_level(logging.ERROR):
            got = await self.received(self.bus(), fields)
        assert got == []
        assert "needs RedisStreamsBusConfig(serializer=...)" in caplog.text
