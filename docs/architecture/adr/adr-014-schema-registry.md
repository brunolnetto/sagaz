# ADR-014: Schema Registry Integration

## Status

**Deferred** | Date: 2026-01-05

> ⚠️ **Note**: This is an **optional** feature for advanced use cases. 
> For most Sagaz deployments, schemas defined in Python code (Pydantic/dataclasses) 
> are sufficient since consumers import the same library.

## When You Need This

| Scenario | Schema Registry? |
|----------|-----------------|
| Single org using Sagaz library | ❌ Not needed |
| Python-only consumers | ❌ Not needed (use Pydantic) |
| Multi-team with different languages | ✅ Recommended |
| External partners consuming events | ✅ Recommended |
| Strict schema governance requirements | ✅ Recommended |

## Context

Sagaz publishes saga events to message brokers (Kafka, RabbitMQ, Redis). For **advanced** use cases:

1. **Schema Evolution**: Event schemas change over time (new fields, deprecations)
2. **Compatibility**: Consumers need to handle multiple schema versions
3. **Validation**: Invalid events should be caught early
4. **Documentation**: Schemas serve as contracts between services

Without a schema registry (only matters for polyglot/multi-team):

| Problem | Impact |
|---------|--------|
| No schema validation | Invalid events cause runtime failures |
| No version tracking | Breaking changes go undetected |
| No documentation | Consumers guess event structure |
| Tight coupling | All services must deploy simultaneously |

## Decision

We will integrate **Schema Registry** support for saga event serialization, supporting:

1. **Confluent Schema Registry** (Kafka ecosystems)
2. **RedPanda Schema Registry** (lightweight alternative)
3. **AWS Glue Schema Registry** (AWS-native)

### Supported Formats

| Format | Use Case | Status |
|--------|----------|--------|
| **Avro** | Compact, schema evolution | Primary |
| **Protobuf** | Performance, gRPC integration | Secondary |
| **JSON Schema** | Debugging, human readability | Optional |

### Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│  Saga App   │────▶│ Schema Registry │     │    Kafka    │
│  (Producer) │     │  (Validation)   │     │   Broker    │
└──────┬──────┘     └────────┬────────┘     └──────┬──────┘
       │                     │                     │
       │ 1. Register/fetch   │                     │
       │    schema           │                     │
       │◀────────────────────┤                     │
       │                     │                     │
       │ 2. Serialize with   │                     │
       │    schema ID        │                     │
       ├─────────────────────┼────────────────────▶│
       │                     │                     │
       │                     │                     │
┌──────┴──────┐              │              ┌──────┴──────┐
│  Consumer   │◀─────────────┼──────────────│    Kafka    │
│   (Inbox)   │ 3. Deserialize│             │   Broker    │
└─────────────┘   with schema │             └─────────────┘
                              │
                     ┌────────┴────────┐
                     │ Schema Registry │
                     │  (Fetch schema) │
                     └─────────────────┘
```

## Implementation

### Schema Definition (Avro)

```avro
{
  "namespace": "io.sagaz.events",
  "type": "record",
  "name": "SagaEvent",
  "fields": [
    {"name": "event_id", "type": "string"},
    {"name": "event_type", "type": {
      "type": "enum",
      "name": "EventType",
      "symbols": ["SAGA_STARTED", "STEP_COMPLETED", "STEP_FAILED", 
                   "COMPENSATION_STARTED", "COMPENSATION_COMPLETED", 
                   "SAGA_COMPLETED", "SAGA_ROLLED_BACK"]
    }},
    {"name": "saga_id", "type": "string"},
    {"name": "saga_name", "type": "string"},
    {"name": "step_name", "type": ["null", "string"], "default": null},
    {"name": "duration_ms", "type": ["null", "long"], "default": null},
    {"name": "error_type", "type": ["null", "string"], "default": null},
    {"name": "error_message", "type": ["null", "string"], "default": null},
    {"name": "context", "type": {"type": "map", "values": "string"}, "default": {}},
    {"name": "timestamp", "type": "long", "logicalType": "timestamp-millis"},
    {"name": "schema_version", "type": "int", "default": 1}
  ]
}
```

### Serializer Configuration

```python
from sagaz.brokers.kafka import KafkaOutboxBroker
from sagaz.serializers import AvroSerializer

# Configure with Schema Registry
broker = KafkaOutboxBroker(
    bootstrap_servers="kafka:9092",
    serializer=AvroSerializer(
        schema_registry_url="http://schema-registry:8081",
        schema_subject="saga-events-value",
        auto_register=True,  # Register new schemas automatically
    )
)
```

### Compatibility Modes

| Mode | Description | Recommendation |
|------|-------------|----------------|
| BACKWARD | New schema can read old data | ✅ Default |
| FORWARD | Old schema can read new data | For critical paths |
| FULL | Both backward and forward | Maximum safety |
| NONE | No compatibility checks | Development only |

## Alternatives Considered

### Alternative 1: Embedded Schema (No Registry)

Include schema in every message.

**Pros**:
- No external dependency
- Self-describing messages

**Cons**:
- Message size bloat
- No central versioning
- No compatibility checks

**Decision**: Rejected - doesn't scale.

### Alternative 2: Protobuf Only

Use Protobuf without registry.

**Pros**:
- Efficient serialization
- Strong typing

**Cons**:
- No runtime schema evolution
- Requires code regeneration

**Decision**: Protobuf supported, but with registry.

### Alternative 3: Custom Schema Management

Build in-house schema management.

**Pros**:
- Full control
- No vendor dependency

**Cons**:
- Significant effort
- Reinventing the wheel

**Decision**: Rejected - use proven solutions.

## Consequences

### Positive

1. **Schema Evolution**: Add/remove fields safely
2. **Validation**: Catch invalid events at producer
3. **Documentation**: Schemas are living documentation
4. **Compatibility**: Multiple schema versions coexist
5. **Compact**: Avro is space-efficient

### Negative

1. **Complexity**: Additional infrastructure
2. **Latency**: Schema fetch adds milliseconds
3. **Learning curve**: Teams need Avro/Protobuf knowledge
4. **Kafka dependency**: Best with Kafka ecosystem

### Mitigations

| Risk | Mitigation |
|------|------------|
| Latency | Client-side schema caching |
| Complexity | Provide Docker Compose templates |
| Learning curve | Documentation and examples |
| Kafka dependency | JSON Schema fallback for others |

## Implementation Plan

### Phase 1: Core Integration (v2.0.0)
- [ ] Create `AvroSerializer` class
- [ ] Create `ProtobufSerializer` class
- [ ] Schema Registry client wrapper
- [ ] Configuration via `SagaConfig`

### Phase 2: Schema Definitions (v2.0.0)
- [ ] Define core event schemas (Avro)
- [ ] Define core event schemas (Protobuf)
- [ ] Schema evolution documentation

### Phase 3: Tooling (v2.0.1)
- [ ] Schema compatibility checker CLI
- [ ] Schema migration documentation
- [ ] Docker Compose with Schema Registry

## References

- [Confluent Schema Registry](https://docs.confluent.io/platform/current/schema-registry/)
- [RedPanda Schema Registry](https://docs.redpanda.com/docs/manage/schema-registry/)
- [Apache Avro](https://avro.apache.org/)
- [Protocol Buffers](https://protobuf.dev/)
- [ADR-011: CDC Support](adr-011-cdc-support.md)

## Decision Makers

- @brunolnetto (Maintainer)

## Changelog

| Date | Change |
|------|--------|
| 2024-12-27 | Initial proposal |
