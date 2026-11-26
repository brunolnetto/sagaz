# Schema Registry

Sagaz publishes JSON by default. When consumers in other languages need typed contracts,
validated on publish and checked as they evolve, encode events in **Avro** or
**JSON Schema** through a Confluent-compatible schema registry: Confluent, Redpanda, or
Apicurio in compatibility mode. The design is in
[ADR-014](../architecture/adr/adr-014-schema-registry.md).

```bash
pip install 'sagaz[schema-registry]'
```

## Payload schemas

You write the schema of each event type's **payload**: the outbox event's `payload`, or a
choreography event's `data`. Sagaz wraps it in the envelope it publishes.

- **Outbox envelope:** `event_id`, `saga_id`, `aggregate_type`, `aggregate_id`,
  `event_type`, `tenant_id`, `payload` and `timestamp`.
- **Choreography envelope:** `event_type`, `data`, `event_id`, `saga_id`, `created_at`,
  `tenant_id`, `causation_id` and `source`.

```python
ORDER_CREATED = {
    "type": "record",
    "name": "OrderCreated",
    "fields": [
        {"name": "order_id", "type": "string"},
        {"name": "amount", "type": "int"},
    ],
}
```

## Outbox messages

Every broker (Kafka, RabbitMQ, Redis) takes a serializer:

```python
from sagaz.core.outbox.brokers.factory import create_broker
from sagaz.integrations.schema_registry import SchemaRegistrySerializer

serializer = SchemaRegistrySerializer(
    "http://registry:8081",                      # or a client config dict
    payload_schemas={"order.created": ORDER_CREATED},
    format="avro",                               # or "json" for JSON Schema
)
broker = create_broker("kafka", bootstrap_servers="kafka:9092", serializer=serializer)
```

## Choreography events on a bus

Every choreography bus takes a `serializer` in its config. It encodes the whole event
(`event.to_dict()`: data, ids, tenant and trace context), and the bus deserializes what it
consumes with the same serializer:

```python
from sagaz.choreography.buses.kafka import KafkaEventBus, KafkaEventBusConfig

serializer = SchemaRegistrySerializer(
    "http://registry:8081", {"order.created": ORDER_CREATED}, envelope="choreography"
)
bus = KafkaEventBus(KafkaEventBusConfig(serializer=serializer))
# or RabbitMQEventBus(RabbitMQEventBusConfig(serializer=serializer))
# or RedisStreamsEventBus(RedisStreamsBusConfig(serializer=serializer))
```

| Bus | Topic (for the subject) | Where the encoded event goes |
|---|---|---|
| Kafka | `topic` | The message value |
| RabbitMQ | `exchange_name` | The message body, with content type `application/octet-stream` |
| Redis Streams | `stream_name` | An `envelope` field, next to plain `event_type` and `saga_id` fields for inspection |

Without a serializer each bus keeps its own format (JSON, or one Redis field per
attribute). A RabbitMQ or Redis Streams bus with a serializer still reads messages in
that format (JSON bodies, entries without `envelope`), so a bus can switch while messages
are in flight. A Redis entry with an `envelope` needs a serializer to be read; without
one it is logged and skipped.

## Behavior

- **Wire format:** Confluent's: a magic byte, the schema id, then the record.
  `deserialize()` also reads plain JSON, so a topic can carry both during a migration.
- **Subjects:** `<topic>-sagaz.<envelope>.<record name>`, for example
  `order.created-sagaz.outbox.order_created`. One topic can carry several event types,
  and the choreography bus uses a single topic.
- **Registration:** schemas are registered on first use (`auto_register=True`). The
  registry enforces the subject's compatibility mode.
- **Event types without a schema:** publishing fails (`on_missing="error"`), so the
  outbox retries and eventually dead-letters the message. With `on_missing="json"`,
  those event types are published as plain JSON.
- **Mismatches:** a payload that does not match its schema fails on publish.

## CLI

```bash
export SAGAZ_SCHEMA_REGISTRY_URL=http://registry:8081
sagaz schema envelope order.created --payload-schema order_created.avsc   # the full schema
sagaz schema check    order.created --payload-schema order_created.avsc   # compatible?
sagaz schema register order.created --payload-schema order_created.avsc
```

The options are `--format avro|json`, `--envelope outbox|choreography` and `--topic`.
`check` exits with status 1 when the schema is not compatible with the registered
versions, so it can gate CI.
