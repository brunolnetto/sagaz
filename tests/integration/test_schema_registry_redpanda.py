"""Saga events through a real schema registry: Redpanda's (ADR-014, #502)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("confluent_kafka.schema_registry")
kafka = pytest.importorskip("testcontainers.kafka")

from sagaz.core.outbox.brokers.factory import create_broker  # noqa: E402
from sagaz.core.outbox.types import OutboxEvent  # noqa: E402
from sagaz.integrations.schema_registry import (  # noqa: E402
    SchemaRegistrySerializer,
    envelope_schema,
    registry_client,
)

pytestmark = pytest.mark.integration

ORDER = {
    "type": "record",
    "name": "OrderCreated",
    "fields": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "int"}],
}


@pytest.fixture(scope="module")
def registry_url():
    container = kafka.RedpandaContainer()
    try:
        container.start()
    except Exception as exc:  # Docker unavailable
        pytest.skip(f"Redpanda container unavailable: {exc}")
    yield container.get_schema_registry_address()
    container.stop()


async def test_publish_register_and_evolve(registry_url):
    from confluent_kafka.schema_registry import Schema

    serializer = SchemaRegistrySerializer(registry_url, {"order.created": ORDER})
    broker = create_broker("memory", serializer=serializer)
    await broker.connect()
    await broker.publish_event(
        OutboxEvent(
            saga_id="s-1", event_type="order.created", payload={"order_id": "o", "amount": 1}
        )
    )
    (message,) = broker.get_messages("order.created")
    record = await SchemaRegistrySerializer(registry_url, {}).deserialize(
        "order.created", message["message"]
    )
    assert record["payload"] == {"order_id": "o", "amount": 1}

    client = registry_client(registry_url)
    subject = "order.created-sagaz.outbox.order_created"
    assert subject in await client.get_subjects()
    added_optional = {
        **ORDER,
        "fields": [*ORDER["fields"], {"name": "note", "type": ["null", "string"], "default": None}],
    }
    changed_type = {**ORDER, "fields": [{"name": "order_id", "type": "int"}]}
    compatible = Schema(envelope_schema("order.created", added_optional), "AVRO")
    breaking = Schema(envelope_schema("order.created", json.dumps(changed_type)), "AVRO")
    assert await client.test_compatibility(subject, compatible)
    assert not await client.test_compatibility(subject, breaking)
