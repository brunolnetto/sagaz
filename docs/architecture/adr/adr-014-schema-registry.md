# ADR-014: Schema Registry Integration

## Status

**Accepted** | Date: 2026-01-05 | Revised: 2026-11-20 | Target: v2.3.0 ([#502](https://github.com/brunolnetto/sagaz/issues/502))

The first version (deferred, 2026-01-05) planned Avro and Protobuf serializers configured
through `SagaConfig`. This revision fixes the scope against the code as of v2.2.0: the
outbox brokers and the choreography buses.

## When You Need This

| Scenario | Schema Registry? |
|----------|-----------------|
| Single org using Sagaz library | ❌ Not needed |
| Python-only consumers | ❌ Not needed (use Pydantic) |
| Multi-team with different languages | ✅ Recommended |
| External partners consuming events | ✅ Recommended |
| Strict schema governance requirements | ✅ Recommended |

## Context

Sagaz publishes events in two places, both as JSON today:

- **Outbox messages:** `BaseBroker.publish_event` builds one envelope for every broker
  (Kafka, RabbitMQ, Redis): `event_id`, `saga_id`, `aggregate_type`, `aggregate_id`,
  `event_type`, `tenant_id`, `payload` and `timestamp`. The topic defaults to the
  event type.
- **Choreography events on the Kafka bus:** `Event.to_dict()`, with `event_type`, `data`,
  `event_id`, `saga_id`, `created_at`, `tenant_id`, `causation_id` and `source`. They go
  on one topic shared by every event type.

Teams in other languages need the shapes as contracts, validated on publish, with
compatibility checked as they evolve.

## Decision

Pluggable **event serializers** with a **Confluent-compatible schema registry**
implementation. It works with the Confluent Schema Registry, the Redpanda registry, and
Apicurio in Confluent-compatibility mode.

### Scope (v2.3.0)

- **Outbox messages, every broker:** `BaseBroker.publish_event` serializes through
  `broker.serializer`. The default `JsonEventSerializer` keeps today's bytes.
- **Choreography events on the Kafka bus:** through `KafkaEventBusConfig.serializer`.
  The RabbitMQ and Redis Streams buses keep JSON for now.
- **Out of scope:** the saga log export to Fluss (ADR-013), which has its own table
  schema, Protobuf, and the AWS Glue registry.

### Schemas

- **What users write:** the schema of each event type's **payload** (outbox `payload`,
  or choreography `data`), in Avro or JSON Schema. Sagaz wraps it in the envelope
  schema, so the envelope's fields are defined once, by sagaz.
- **Record names:** derived from the event type, for example `order.created` becomes
  `sagaz.outbox.order_created` or `sagaz.choreography.order_created`.
- **Subjects:** `TopicRecordNameStrategy` (`<topic>-<record name>`). The choreography
  bus carries every event type on one topic, and a subject per topic would force every
  type into one schema.
- **Registration:** schemas are auto-registered by default. The registry enforces the
  subject's compatibility mode, BACKWARD by default.
- **Event types without a schema:** an error by default (`on_missing="error"`), so
  publishing fails, the outbox retries, and the message eventually reaches the dead
  letter queue. With `on_missing="json"`, they are published as JSON.

### Wire format and consumers

- **Wire format:** Confluent's: a magic byte 0, the 4-byte schema id, then the encoded
  record.
- **`deserialize()`:** decodes registry-encoded and plain JSON messages alike. Mixed
  topics keep working during a migration.
- **Kafka bus consumers:** they deserialize with the configured serializer.

### Library

`confluent-kafka`'s schema registry client and its **async** Avro and JSON Schema
serializers (`sagaz[schema-registry]`). No call blocks the event loop. Its mock
registry client backs the unit tests.

### Tooling

`sagaz schema` has three commands:

- **`envelope`:** prints the full schema of an event type.
- **`check`:** tests a payload schema against the registered versions of its subject.
- **`register`:** registers it.

## Alternatives Considered

- **Embedded schemas (no registry):** this makes every message larger and offers no
  compatibility checks. Rejected.
- **Protobuf only:** it needs generated code and is less natural for Python-first
  users. Possible later.
- **Custom schema management:** this would reinvent a registry. Rejected.
- **`python-schema-registry-client`:** an async third-party client. The official client
  now has async serializers and a mock for tests, so it is preferred.

## Consequences

- **Positive:** typed, validated contracts for consumers in any language, with schema
  evolution checked by the registry.
- **Positive:** this is opt-in. JSON stays the default, and existing consumers are
  unaffected.
- **Negative:** another service to run (the registry), and `confluent-kafka` as an
  optional dependency.
- **Negative:** a payload that does not match its schema fails on publish. That is the
  point, but it surfaces as outbox retries and DLQ entries.

## References

- [Confluent Schema Registry](https://docs.confluent.io/platform/current/schema-registry/)
- [Redpanda Schema Registry](https://docs.redpanda.com/current/manage/schema-reg/)
- [Apache Avro](https://avro.apache.org/)
- [JSON Schema](https://json-schema.org/)
- [ADR-029: Saga Choreography](adr-029-saga-choreography.md)

## Decision Makers

- @brunolnetto (Maintainer)
