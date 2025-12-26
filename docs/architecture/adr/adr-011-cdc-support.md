# ADR-011: CDC (Change Data Capture) Support

## Status

**Proposed** - Design phase

## Context

The transactional outbox pattern using polling workers has throughput limitations:
- **Current**: 1,000-5,000 events/sec
- **Target with CDC**: 50,000+ events/sec

For high-throughput scenarios, Change Data Capture (CDC) provides a more scalable approach by streaming database changes directly from the Write-Ahead Log (WAL).

## Current Architecture (Polling)

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│ Application │ ──► │   saga_outbox   │ ◄── │   Workers   │
│             │     │   (INSERT)      │     │  (polling)  │
└─────────────┘     └─────────────────┘     └─────────────┘
                           │                       │
                           └───────────────────────┘
                              SELECT ... FOR UPDATE
                              UPDATE status = 'sent'
```

**Bottleneck**: Database contention from polling + updates.

## Proposed Architecture (CDC)

```
┌─────────────┐     ┌─────────────────┐     ┌───────────────┐     ┌─────────────┐
│ Application │ ──► │   saga_outbox   │ ──► │  CDC Capture  │ ──► │   Broker    │
│             │     │   (INSERT)      │     │  (WAL stream) │     │(Kafka/etc)  │
└─────────────┘     └─────────────────┘     └───────────────┘     └─────────────┘
                                                    │
                                                    │ No polling!
                                                    │ No FOR UPDATE!
                                                    ▼
                                            ┌───────────────┐
                                            │   Debezium    │
                                            │   Connector   │
                                            └───────────────┘
```

---

## Design Principles

### 1. Maintain Exactly-Once Semantics

CDC captures WAL changes, which are already committed transactions. Combined with consumer inbox pattern on receiving side, we maintain exactly-once.

### 2. Backward Compatible

- Same `saga_outbox` table schema
- Same `OutboxEvent` types
- Application code unchanged
- Only worker deployment changes

### 3. Hybrid Support

Allow both modes:
- **Polling mode**: Simple deployments, low volume
- **CDC mode**: High throughput requirements

### 4. Pluggable CDC Backends

| Backend | Use Case |
|---------|----------|
| Debezium (Kafka Connect) | Production, Kafka ecosystems |
| pg_logical (native) | PostgreSQL-only, simpler |
| AWS DMS | AWS deployments |

---

## Implementation Approach

### Phase 1: Schema Preparation

Ensure `saga_outbox` supports CDC:

```sql
-- Already have: INSERT triggers natural CDC events

-- Add: publication for logical replication
CREATE PUBLICATION saga_outbox_pub FOR TABLE saga_outbox;

-- Add: replication slot
SELECT pg_create_logical_replication_slot('sage_cdc', 'pgoutput');
```

### Phase 2: Debezium Connector

Create Debezium connector configuration:

```json
{
  "name": "sage-outbox-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgresql",
    "database.port": "5432",
    "database.user": "replication_user",
    "database.password": "${REPLICATION_PASSWORD}",
    "database.dbname": "saga_db",
    "database.server.name": "sage",
    "table.include.list": "public.saga_outbox",
    "plugin.name": "pgoutput",
    "publication.name": "saga_outbox_pub",
    
    "transforms": "outbox",
    "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
    "transforms.outbox.table.field.event.id": "event_id",
    "transforms.outbox.table.field.event.key": "aggregate_id",
    "transforms.outbox.table.field.event.payload": "payload",
    "transforms.outbox.route.topic.replacement": "saga.events.${routedByValue}",
    "transforms.outbox.route.by.field": "event_type"
  }
}
```

### Phase 3: CDC Worker (Alternative to Polling)

```python
class CDCOutboxWorker:
    """
    CDC-based outbox worker.
    
    Instead of polling the database, consumes CDC events from Kafka.
    """
    
    def __init__(
        self,
        cdc_consumer: KafkaConsumer,
        broker: MessageBroker,
        inbox_storage: Optional[ConsumerInbox] = None,
    ):
        self.cdc_consumer = cdc_consumer
        self.broker = broker
        self.inbox_storage = inbox_storage
    
    async def process_cdc_event(self, cdc_event: dict):
        """Process a CDC event from Debezium."""
        # Extract outbox event from CDC payload
        event = self._parse_cdc_event(cdc_event)
        
        # Idempotency check (optional, for exactly-once)
        if self.inbox_storage:
            if await self.inbox_storage.exists(event.event_id):
                return  # Already processed
        
        # Publish to target broker
        await self.broker.publish_event(event)
        
        # Mark as processed
        if self.inbox_storage:
            await self.inbox_storage.mark_processed(event.event_id)
    
    async def run(self):
        """Main processing loop."""
        async for message in self.cdc_consumer:
            await self.process_cdc_event(message.value)
            await self.cdc_consumer.commit()
```

### Phase 4: No Status Updates Needed

With CDC, we don't need to update event status in the database:

| Polling Mode | CDC Mode |
|-------------|----------|
| INSERT → pending | INSERT (CDC captured) |
| SELECT FOR UPDATE → claimed | ❌ Not needed |
| UPDATE → sent | ❌ Not needed |

The CDC connector captures INSERT, that's all we need.

---

## Table Schema Changes (Optional)

For CDC optimization, consider:

```sql
-- Option A: Keep current schema (simpler)
-- CDC captures all INSERTs, we filter in transforms

-- Option B: Outbox-specific table (recommended for CDC)
CREATE TABLE saga_outbox_cdc (
    event_id        UUID PRIMARY KEY,
    aggregate_type  VARCHAR(255) NOT NULL,
    aggregate_id    VARCHAR(255) NOT NULL,
    event_type      VARCHAR(255) NOT NULL,
    payload         JSONB NOT NULL,
    headers         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
    -- No status column! CDC handles delivery.
);

-- Delete after CDC capture (configurable retention)
-- Debezium can be configured to delete-after-capture
```

---

## Deployment Options

### Option 1: Debezium + Kafka Connect (Recommended for Kafka users)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  PostgreSQL  │ ──► │ Kafka Connect│ ──► │    Kafka     │
│              │     │  + Debezium  │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
```

**Pros**: Battle-tested, high throughput, managed in cloud  
**Cons**: Requires Kafka infrastructure

### Option 2: Debezium Server + Redis Streams

**Debezium Server** is a standalone runtime that outputs directly to Redis Streams without Kafka:

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│  PostgreSQL  │ ──► │ Debezium Server │ ──► │Redis Streams │
│              │     │   (standalone)  │     │              │
└──────────────┘     └─────────────────┘     └──────────────┘
```

#### Configuration (application.properties)

```properties
# Debezium Server Redis Sink Configuration
debezium.sink.type=redis
debezium.sink.redis.address=redis://localhost:6379
debezium.sink.redis.stream.name=sage.outbox.events
debezium.sink.redis.null.key=null
debezium.sink.redis.null.value=tombstone

# Source: PostgreSQL
debezium.source.connector.class=io.debezium.connector.postgresql.PostgresConnector
debezium.source.database.hostname=postgresql
debezium.source.database.port=5432
debezium.source.database.user=replication_user
debezium.source.database.password=${REPLICATION_PASSWORD}
debezium.source.database.dbname=saga_db
debezium.source.database.server.name=sage
debezium.source.table.include.list=public.saga_outbox
debezium.source.plugin.name=pgoutput
debezium.source.publication.name=saga_outbox_pub

# Outbox Event Router transform
debezium.transforms=outbox
debezium.transforms.outbox.type=io.debezium.transforms.outbox.EventRouter
debezium.transforms.outbox.table.field.event.id=event_id
debezium.transforms.outbox.table.field.event.key=aggregate_id
debezium.transforms.outbox.table.field.event.payload=payload
debezium.transforms.outbox.route.by.field=event_type
```

#### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: debezium-server-redis
spec:
  replicas: 1  # Single instance for WAL streaming
  template:
    spec:
      containers:
        - name: debezium-server
          image: quay.io/debezium/server:2.4
          volumeMounts:
            - name: config
              mountPath: /debezium/conf
          env:
            - name: REPLICATION_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: postgres-credentials
                  key: replication-password
      volumes:
        - name: config
          configMap:
            name: debezium-redis-config
```

**Pros**: No Kafka required, low latency (~1ms), simple infrastructure  
**Cons**: Redis persistence configuration required, less mature than Kafka sink

### Option 3: Debezium Server + RabbitMQ

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│  PostgreSQL  │ ──► │ Debezium Server │ ──► │   RabbitMQ   │
│              │     │   (standalone)  │     │              │
└──────────────┘     └─────────────────┘     └──────────────┘
```

#### Configuration (application.properties)

```properties
# Debezium Server RabbitMQ Sink Configuration
debezium.sink.type=rabbitmq
debezium.sink.rabbitmq.connection.host=rabbitmq
debezium.sink.rabbitmq.connection.port=5672
debezium.sink.rabbitmq.connection.username=sage
debezium.sink.rabbitmq.connection.password=${RABBITMQ_PASSWORD}

# Exchange configuration
debezium.sink.rabbitmq.exchange=sage.cdc.exchange
debezium.sink.rabbitmq.routingKey=saga.outbox.${routedByValue}
debezium.sink.rabbitmq.autoCreateExchange=true
debezium.sink.rabbitmq.exchangeType=topic

# Source: PostgreSQL (same as above)
debezium.source.connector.class=io.debezium.connector.postgresql.PostgresConnector
debezium.source.database.hostname=postgresql
debezium.source.database.port=5432
debezium.source.database.user=replication_user
debezium.source.database.password=${REPLICATION_PASSWORD}
debezium.source.database.dbname=saga_db
debezium.source.database.server.name=sage
debezium.source.table.include.list=public.saga_outbox
debezium.source.plugin.name=pgoutput
debezium.source.publication.name=saga_outbox_pub

# Outbox transform
debezium.transforms=outbox
debezium.transforms.outbox.type=io.debezium.transforms.outbox.EventRouter
```

**Pros**: Familiar RabbitMQ semantics, flexible routing, no Kafka needed  
**Cons**: No log compaction, requires durable queues for reliability

### Option 4: Native PostgreSQL Logical Replication

```python
# Using psycopg2/asyncpg logical replication
async def stream_wal_changes():
    conn = await asyncpg.connect(replication='database')
    async with conn.cursor() as cur:
        await cur.execute("START_REPLICATION SLOTsagaz_cdc ...")
        async for message in cur:
            yield parse_wal_message(message)
```

**Pros**: No external dependencies  
**Cons**: More complex to implement correctly

### Option 5: Cloud-Native CDC

- **AWS**: DMS + Kinesis
- **GCP**: Datastream
- **Azure**: Data Factory CDC

---

## Broker Selection Decision Matrix

Choose the right CDC sink based on your requirements:

### Quick Reference

| Requirement | Kafka | Redis Streams | RabbitMQ |
|-------------|-------|---------------|----------|
| **Throughput** | 100K+/sec | 50K+/sec | 30K+/sec |
| **Latency** | 10-50ms | 1-10ms | 5-20ms |
| **Ordering** | Per partition | Per stream | Per queue |
| **Replay capability** | ✅ Excellent | ⚠️ Limited | ❌ None |
| **Infrastructure complexity** | High | Low | Medium |
| **Operational maturity** | ✅ Mature | ⚠️ Newer | ✅ Mature |
| **Debezium support** | ✅ Native | ✅ Server | ✅ Server |

### Detailed Comparison

| Feature | Kafka Connect | Debezium Server (Redis) | Debezium Server (RabbitMQ) |
|---------|---------------|-------------------------|----------------------------|
| **Architecture** | Distributed workers | Single process | Single process |
| **Horizontal scaling** | ✅ Automatic | ⚠️ Manual partitioning | ⚠️ Manual sharding |
| **Exactly-once** | ✅ Native | ⚠️ Consumer inbox | ⚠️ Consumer inbox |
| **Log compaction** | ✅ Yes | ❌ No | ❌ No |
| **Message replay** | ✅ Offset reset | ⚠️ Stream history | ❌ Not supported |
| **Backpressure** | ✅ Automatic | ✅ XADD blocking | ⚠️ Queue limits |
| **Dead letter handling** | ✅ Native | ⚠️ Manual | ✅ Native |
| **Schema registry** | ✅ Confluent/Apicurio | ❌ JSON only | ❌ JSON only |

### When to Choose Each Sink

#### ✅ Choose **Kafka** when:
- Throughput exceeds 50K events/sec
- Need replay capability for debugging/recovery
- Already have Kafka infrastructure
- Need log compaction for state snapshots
- Multiple consumers with different speeds
- Enterprise/compliance requirements

#### ✅ Choose **Redis Streams** when:
- Already using Redis for caching/sessions
- Need lowest latency (<10ms)
- Simpler infrastructure preferred
- Throughput 10-50K events/sec
- Consumers process in real-time (no replay needed)
- Development/staging environments

#### ✅ Choose **RabbitMQ** when:
- Already using RabbitMQ for messaging
- Need flexible routing (topic/fanout patterns)
- Throughput 5-30K events/sec
- Familiar with AMQP semantics
- Need dead-letter queues natively
- Existing RabbitMQ expertise on team

### Decision Flowchart

```
                     ┌─────────────────────────────┐
                     │ Do you need >50K events/sec │
                     │   or message replay?        │
                     └─────────────┬───────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                   YES                           NO
                    │                             │
                    ▼                             ▼
           ┌────────────────┐        ┌─────────────────────────┐
           │  Use Kafka     │        │ Do you already have     │
           │  (best replay) │        │ Redis in your stack?    │
           └────────────────┘        └───────────┬─────────────┘
                                                 │
                                  ┌──────────────┴──────────────┐
                                  │                             │
                                 YES                           NO
                                  │                             │
                                  ▼                             ▼
                         ┌────────────────┐        ┌─────────────────────────┐
                         │ Use Redis      │        │ Need complex routing    │
                         │ Streams        │        │ or dead-letter queues?  │
                         │ (lowest latency)        └───────────┬─────────────┘
                         └────────────────┘                    │
                                                ┌──────────────┴──────────────┐
                                                │                             │
                                               YES                           NO
                                                │                             │
                                                ▼                             ▼
                                       ┌────────────────┐        ┌────────────────┐
                                       │ Use RabbitMQ   │        │ Use Redis      │
                                       │ (routing power)│        │ Streams        │
                                       └────────────────┘        │ (simpler)      │
                                                                 └────────────────┘
```

### Cost Considerations

| Broker | Self-Hosted | Managed Service |
|--------|-------------|-----------------|
| **Kafka** | High (ZK/KRaft, brokers) | Confluent Cloud, AWS MSK: $$$ |
| **Redis** | Low (single node possible) | Redis Cloud, ElastiCache: $$ |
| **RabbitMQ** | Medium (clustering) | CloudAMQP, Amazon MQ: $$ |

---

## Migration Path

### Stage 1: Parallel Running

```
                    ┌─────────────────┐
                    │   saga_outbox   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────────┐  ┌─────────┐
        │ Polling  │  │ CDC Capture  │  │ CDC     │
        │ Workers  │  │              │  │ Workers │
        │ (legacy) │  │              │  │ (new)   │
        └──────────┘  └──────────────┘  └─────────┘
                             │              │
                             └──────────────┘
                              Both publish to
                              same broker topic
```

### Stage 2: Cutover

1. Stop polling workers
2. Verify CDC workers are processing
3. Remove polling worker deployment

### Stage 3: Cleanup

1. Remove `status` column (optional)
2. Simplify table to CDC-optimized schema

---

## Performance Expectations

| Mode | Throughput | Latency |
|------|-----------|---------|
| Polling | 1-5K/sec | 100-1000ms |
| CDC (Debezium) | 50-100K/sec | 10-100ms |
| CDC (native) | 20-50K/sec | 10-50ms |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| WAL retention overflow | Monitor `pg_replication_slots`, alert on lag |
| Debezium connector failures | Use Kafka Connect distributed mode, monitoring |
| Duplicate events (restart) | Consumer inbox pattern on receiving end |
| Schema changes break CDC | Use Debezium schema registry integration |

---

## Monitoring Integration

CDC requires enhanced monitoring via Prometheus and Grafana.

### Prometheus Metrics (CDC-specific)

| Metric | Type | Description |
|--------|------|-------------|
| `cdc_lag_seconds` | Gauge | Replication lag from WAL to broker |
| `cdc_events_captured_total` | Counter | Events captured from WAL |
| `cdc_events_published_total` | Counter | Events published to broker |
| `cdc_connector_status` | Gauge | Debezium connector health (1=running) |
| `cdc_replication_slot_lag_bytes` | Gauge | PostgreSQL replication slot lag |

### Prometheus Alerts

```yaml
groups:
  - name: cdc-alerts
    rules:
      - alert: CDCLagHigh
        expr: cdc_lag_seconds > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "CDC replication lag is high"
          
      - alert: CDCConnectorDown
        expr: cdc_connector_status == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Debezium connector is not running"
          
      - alert: ReplicationSlotLagCritical
        expr: cdc_replication_slot_lag_bytes > 1073741824  # 1GB
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Replication slot lag exceeds 1GB - risk of WAL overflow"
```

### Grafana Dashboard Panels

| Panel | Query | Purpose |
|-------|-------|---------|
| CDC Throughput | `rate(cdc_events_published_total[5m])` | Events/sec via CDC |
| Replication Lag | `cdc_lag_seconds` | End-to-end latency |
| Slot Lag | `cdc_replication_slot_lag_bytes / 1024 / 1024` | MB of WAL pending |
| Connector Status | `cdc_connector_status` | Up/down status |
| CDC vs Polling | Compare `cdc_*` vs `outbox_*` metrics | Migration comparison |

### Integration with Existing Dashboards

Update existing Grafana dashboards to include:

1. **Outbox Overview Dashboard**
   - Add "CDC Mode" toggle
   - Show CDC metrics when enabled
   - Compare throughput: polling vs CDC

2. **Health Dashboard**
   - Add CDC connector status
   - Add replication slot lag
   - Add WAL usage alerts

---

## Implementation Phases

| Phase | Scope | Effort |
|-------|-------|--------|
| 1. Design & ADR | This document | ✅ Done |
| 2. Schema prep | Publication, replication slot | 2 hours |
| 3. Debezium config | Connector JSON, K8s deployment | 4 hours |
| 4. CDC Worker | Python consumer, processing | 8 hours |
| 5. Testing | Integration tests, benchmarks | 8 hours |
| 6. Documentation | Migration guide, runbooks | 4 hours |

**Total estimate**: ~26 hours (3-4 days)

---

## Decision

**Deferred** - To be implemented when:
- Throughput requirements exceed 5K events/sec
- Team has Debezium expertise
- Infrastructure supports any of: Kafka Connect, Redis, or RabbitMQ

For now, polling workers are sufficient for most use cases. CDC provides a clear upgrade path with **three broker options**:
- **Kafka**: Highest throughput, best replay
- **Redis Streams**: Lowest latency, simplest setup
- **RabbitMQ**: Flexible routing, familiar AMQP

---

## References

### Debezium Documentation
- [Debezium Outbox Event Router](https://debezium.io/documentation/reference/transformations/outbox-event-router.html)
- [Debezium Server](https://debezium.io/documentation/reference/operations/debezium-server.html)
- [Debezium Redis Sink](https://debezium.io/documentation/reference/operations/debezium-server.html#_redis_stream)
- [Debezium RabbitMQ Sink](https://debezium.io/documentation/reference/operations/debezium-server.html#_rabbitmq)

### PostgreSQL
- [PostgreSQL Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)

### Redis Streams
- [Redis Streams Introduction](https://redis.io/docs/data-types/streams/)
- [Redis Streams Tutorial](https://redis.io/docs/data-types/streams-tutorial/)

### RabbitMQ
- [RabbitMQ Reliability Guide](https://www.rabbitmq.com/reliability.html)
- [RabbitMQ Dead Letter Exchanges](https://www.rabbitmq.com/dlx.html)

### Patterns
- [Microservices Patterns: Transactional Outbox](https://microservices.io/patterns/data/transactional-outbox.html)
