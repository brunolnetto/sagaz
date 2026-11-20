"""Saga events through a schema registry (ADR-014, #502), with the mock registry client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

pytest.importorskip("confluent_kafka.schema_registry")

from confluent_kafka.schema_registry._async.mock_schema_registry_client import (  # noqa: E402
    AsyncMockSchemaRegistryClient,
)

from sagaz.choreography.events import Event  # noqa: E402
from sagaz.cli.app import cli  # noqa: E402
from sagaz.core.outbox.brokers.factory import create_broker  # noqa: E402
from sagaz.core.outbox.serialization import EventSerializer, JsonEventSerializer  # noqa: E402
from sagaz.core.outbox.types import OutboxEvent  # noqa: E402
from sagaz.integrations.schema_registry import (  # noqa: E402
    SchemaError,
    SchemaRegistrySerializer,
    envelope_schema,
    record_name,
)

ORDER_AVRO = {
    "type": "record",
    "name": "OrderCreated",
    "fields": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "int"}],
}
ORDER_JSON = {
    "type": "object",
    "properties": {"order_id": {"type": "string"}, "amount": {"type": "integer"}},
    "required": ["order_id"],
}


@pytest.fixture
def registry():
    return AsyncMockSchemaRegistryClient({"url": "mock://registry"})


def outbox_event(**payload) -> OutboxEvent:
    return OutboxEvent(
        saga_id="s-1",
        event_type="order.created",
        payload=payload or {"order_id": "o-1", "amount": 40},
        tenant_id="acme",
    )


class TestEnvelopes:
    def test_names(self):
        assert record_name("order.created") == "order_created"
        assert record_name("3d-printed") == "_3d_printed"

    def test_avro_outbox_envelope(self):
        schema = json.loads(envelope_schema("order.created", ORDER_AVRO))
        assert (schema["namespace"], schema["name"]) == ("sagaz.outbox", "order_created")
        fields = {f["name"]: f for f in schema["fields"]}
        assert fields["payload"]["type"] == ORDER_AVRO
        assert fields["tenant_id"] == {
            "name": "tenant_id",
            "type": ["null", "string"],
            "default": None,
        }
        assert "default" not in fields["event_id"]

    def test_json_choreography_envelope(self):
        schema = json.loads(
            envelope_schema(
                "order.created", json.dumps(ORDER_JSON), format="json", envelope="choreography"
            )
        )
        assert schema["title"] == "sagaz.choreography.order_created"
        assert schema["properties"]["data"] == ORDER_JSON
        assert set(schema["required"]) == {"event_type", "data", "event_id", "created_at"}

    def test_an_avro_payload_must_be_a_record(self):
        with pytest.raises(SchemaError, match="must be a record"):
            envelope_schema("x", {"type": "string"})


class TestOutbox:
    @pytest.mark.parametrize(
        ("fmt", "payload_schema"), [("avro", ORDER_AVRO), ("json", ORDER_JSON)]
    )
    async def test_a_broker_publishes_registry_encoded_envelopes(
        self, registry, fmt, payload_schema
    ):
        serializer = SchemaRegistrySerializer(
            registry, {"order.created": payload_schema}, format=fmt
        )
        assert isinstance(serializer, EventSerializer)
        broker = create_broker("memory", serializer=serializer)
        await broker.connect()
        event = outbox_event()
        await broker.publish_event(event)
        (message,) = broker.get_messages("order.created")
        value = message["message"]
        assert value[:1] == b"\x00"  # Confluent wire format: magic byte, schema id, record
        record = await serializer.deserialize("order.created", value)
        assert record["payload"] == {"order_id": "o-1", "amount": 40}
        assert (record["event_id"], record["tenant_id"]) == (event.event_id, "acme")
        assert await registry.get_subjects() == ["order.created-sagaz.outbox.order_created"]

    async def test_a_payload_that_breaks_its_schema_is_refused(self, registry):
        serializer = SchemaRegistrySerializer(registry, {"order.created": ORDER_AVRO})
        broker = create_broker("memory", serializer=serializer)
        await broker.connect()
        with pytest.raises(Exception):  # noqa: B017 - the Avro writer's own error type
            await broker.publish_event(outbox_event(order_id="o-1", amount="forty"))

    async def test_event_types_without_a_schema(self, registry):
        strict = SchemaRegistrySerializer(registry, {})
        with pytest.raises(SchemaError, match="no schema for event type 'order.created'"):
            await strict.serialize("t", {"x": 1}, "order.created")
        lenient = SchemaRegistrySerializer(registry, {}, on_missing="json")
        assert await lenient.serialize("t", {"x": 1}, "order.created") == b'{"x": 1}'

    async def test_plain_json_still_deserializes(self, registry):
        serializer = SchemaRegistrySerializer(registry, {"order.created": ORDER_AVRO})
        assert await serializer.deserialize("t", b'{"legacy": true}') == {"legacy": True}

    async def test_unregistered_schemas_are_not_registered_on_demand(self, registry):
        serializer = SchemaRegistrySerializer(
            registry, {"order.created": ORDER_AVRO}, auto_register=False
        )
        with pytest.raises(Exception):  # noqa: B017 - the registry client's "not found"
            await serializer.serialize("order.created", {"payload": {}}, "order.created")

    async def test_json_is_the_default(self):
        broker = create_broker("memory")
        assert isinstance(broker.serializer, JsonEventSerializer)
        await broker.connect()
        await broker.publish_event(outbox_event())
        (message,) = broker.get_messages("order.created")
        assert json.loads(message["message"])["payload"]["amount"] == 40


class TestChoreographyBus:
    async def test_the_kafka_bus_encodes_and_decodes_through_the_registry(self, registry):
        from sagaz.choreography.buses.kafka import KafkaEventBus, KafkaEventBusConfig

        serializer = SchemaRegistrySerializer(
            registry, {"order.created": ORDER_AVRO}, envelope="choreography"
        )
        bus = KafkaEventBus(KafkaEventBusConfig(serializer=serializer))
        producer = AsyncMock()
        bus._producer = producer
        event = Event("order.created", {"order_id": "o-1", "amount": 40}, saga_id="s-1")
        await bus.publish(event)
        value = producer.send_and_wait.call_args.kwargs["value"]
        assert value[:1] == b"\x00"
        received = []

        async def handler(e):
            received.append(e)

        bus.subscribe("order.created", handler)
        await bus._dispatch(value)
        assert received[0].data == {"order_id": "o-1", "amount": 40}
        assert received[0].event_id == event.event_id
        assert await registry.get_subjects() == [
            "sagaz.choreography-sagaz.choreography.order_created"
        ]


class TestCli:
    @pytest.fixture
    def payload(self, tmp_path):
        path = tmp_path / "order.avsc"
        path.write_text(json.dumps(ORDER_AVRO))
        return path

    def test_envelope(self, payload):
        result = CliRunner().invoke(
            cli, ["schema", "envelope", "order.created", "--payload-schema", str(payload)]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["name"] == "order_created"
        bad = payload.parent / "bad.json"
        bad.write_text('{"type": "string"}')
        refused = CliRunner().invoke(cli, ["schema", "envelope", "x", "--payload-schema", str(bad)])
        assert refused.exit_code != 0
        assert "must be a record" in refused.output

    def test_check_and_register(self, payload, registry, monkeypatch):
        monkeypatch.setattr(
            "sagaz.integrations.schema_registry.registry_client", lambda _: registry
        )
        args = ["order.created", "--payload-schema", str(payload), "--registry", "mock://r"]
        first = CliRunner().invoke(cli, ["schema", "check", *args])
        assert "not registered yet" in first.output
        registered = CliRunner().invoke(cli, ["schema", "register", *args])
        assert registered.exit_code == 0, registered.output
        assert "order.created-sagaz.outbox.order_created: schema id" in registered.output
        # The mock client has no compatibility endpoint: answer as a registry would.
        registry.test_compatibility = AsyncMock(side_effect=[True, False])
        same = CliRunner().invoke(cli, ["schema", "check", *args])
        assert same.exit_code == 0
        assert ": compatible" in same.output
        breaking = payload.parent / "breaking.avsc"
        breaking.write_text(
            json.dumps({**ORDER_AVRO, "fields": [{"name": "order_id", "type": "int"}]})
        )
        incompatible = CliRunner().invoke(
            cli,
            [
                "schema",
                "check",
                "order.created",
                "--payload-schema",
                str(breaking),
                "--registry",
                "mock://r",
            ],
        )
        assert incompatible.exit_code == 1
        assert "NOT compatible" in incompatible.output


class TestClient:
    def test_clients_from_a_url_or_a_config(self, registry):
        from confluent_kafka.schema_registry._async.schema_registry_client import (
            AsyncSchemaRegistryClient,
        )

        from sagaz.integrations.schema_registry import registry_client

        assert isinstance(registry_client("http://registry:8081"), AsyncSchemaRegistryClient)
        assert isinstance(registry_client({"url": "http://r:8081"}), AsyncSchemaRegistryClient)
        assert registry_client(registry) is registry

    def test_without_confluent_kafka(self, monkeypatch):
        import sys

        from sagaz.core.exceptions import MissingDependencyError
        from sagaz.integrations.schema_registry import registry_client

        monkeypatch.setitem(sys.modules, "confluent_kafka.schema_registry", None)
        with pytest.raises(MissingDependencyError, match="confluent-kafka"):
            registry_client("http://registry:8081")

    async def test_json_serializer_round_trip(self):
        serializer = JsonEventSerializer()
        data = await serializer.serialize("t", {"a": 1}, "x")
        assert await serializer.deserialize("t", data) == {"a": 1}
