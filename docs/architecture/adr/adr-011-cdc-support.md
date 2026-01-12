# ADR-011: CDC (Change Data Capture) Support

## Status

**Proposed** | Date: 2026-01-05 | Priority: Low | Target: Future

## Dependencies

**Prerequisites**:
- ADR-016: Unified Storage Layer (needs unified PostgreSQL backend)

**Synergies**:
- ADR-025: Event Triggers (CDC events can trigger sagas)

**Roadmap**: **Phase 5 (Future/Optional)** - Only for 50K+ events/sec throughput

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

### Phase 3: Extend Existing OutboxWorker with CDC Mode

Instead of creating a separate worker, extend the existing `OutboxWorker` with a `mode` parameter:

```python
from enum import Enum

class WorkerMode(Enum):
    """Outbox worker operation mode."""
    POLLING = "polling"  # Traditional database polling
    CDC = "cdc"          # Change Data Capture stream consumption

class OutboxWorker:
    """
    Unified outbox worker supporting both polling and CDC modes.
    
    Polling mode: Polls database for pending events (traditional)
    CDC mode: Consumes CDC events from stream (high-throughput)
    """
    
    def __init__(
        self,
        storage: OutboxStorage,
        broker: MessageBroker,
        config: OutboxConfig | None = None,
        worker_id: str | None = None,
        mode: WorkerMode = WorkerMode.POLLING,
        cdc_consumer: Optional[Any] = None,  # Kafka/Redis consumer for CDC mode
        on_event_published: Callable[[OutboxEvent], Awaitable[None]] | None = None,
        on_event_failed: Callable[[OutboxEvent, Exception], Awaitable[None]] | None = None,
    ):
        """
        Initialize the outbox worker.

        Args:
            storage: Outbox storage (used in polling mode)
            broker: Target message broker for publishing
            config: Worker configuration
            worker_id: Unique worker identifier
            mode: POLLING (default) or CDC
            cdc_consumer: Consumer for CDC events (required if mode=CDC)
            on_event_published: Success callback
            on_event_failed: Failure callback
        """
        self.storage = storage
        self.broker = broker
        self.config = config or OutboxConfig()
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.mode = mode
        self.cdc_consumer = cdc_consumer
        
        # Validate CDC mode requirements
        if self.mode == WorkerMode.CDC and not self.cdc_consumer:
            raise ValueError("cdc_consumer required when mode=CDC")
        
        self._state_machine = OutboxStateMachine(max_retries=self.config.max_retries)
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        self._on_event_published = on_event_published
        self._on_event_failed = on_event_failed
        
        # Metrics
        self._events_processed = 0
        self._events_failed = 0
        self._events_dead_lettered = 0
    
    async def _run_processing_loop(self) -> None:
        """Main processing loop - delegates to mode-specific implementation."""
        if self.mode == WorkerMode.POLLING:
            await self._run_polling_loop()
        else:
            await self._run_cdc_loop()
    
    async def _run_polling_loop(self) -> None:
        """Polling mode: Traditional database polling (existing logic)."""
        while self._running:
            should_break = await self._process_iteration()
            if should_break:
                break
    
    async def _run_cdc_loop(self) -> None:
        """CDC mode: Consume events from CDC stream."""
        logger.info(f"Worker {self.worker_id} running in CDC mode")
        
        try:
            async for message in self.cdc_consumer:
                if not self._running:
                    break
                
                await self._process_cdc_message(message)
                
        except asyncio.CancelledError:
            logger.info(f"CDC worker {self.worker_id} cancelled")
    
    async def _process_cdc_message(self, message: Any) -> None:
        """
        Process a single CDC message from Debezium.
        
        CDC message format (Debezium outbox transform):
        {
            "id": "event-uuid",
            "aggregateType": "order",
            "aggregateId": "ORD-123",
            "type": "OrderCreated",
            "payload": {"order_id": "ORD-123", ...},
            "timestamp": 1704067200000
        }
        """
        try:
            # Parse CDC event into OutboxEvent
            event = self._parse_cdc_event(message)
            
            # Process the event (same logic as polling mode)
            await self._process_event(event)
            
            # Commit offset (CDC consumer)
            await self._commit_cdc_offset(message)
            
        except Exception as e:
            logger.error(f"Failed to process CDC message: {e}")
            # CDC errors are logged but don't stop the worker
            # Event remains in CDC stream for retry
    
    def _parse_cdc_event(self, message: Any) -> OutboxEvent:
        """
        Parse Debezium CDC message into OutboxEvent.
        
        Supports multiple CDC formats:
        - Debezium outbox transform (recommended)
        - Raw CDC change event
        """
        # Handle Kafka message
        if hasattr(message, 'value'):
            payload = message.value
        else:
            payload = message
        
        # Debezium outbox transform format
        if isinstance(payload, dict) and 'type' in payload:
            return OutboxEvent(
                event_id=payload.get('id', str(uuid.uuid4())),
                saga_id=payload.get('saga_id', payload.get('aggregateId')),
                aggregate_type=payload.get('aggregateType', 'saga'),
                aggregate_id=payload.get('aggregateId'),
                event_type=payload['type'],
                payload=payload.get('payload', {}),
                headers=payload.get('headers', {}),
                status=OutboxStatus.PENDING,  # CDC events are "already claimed"
            )
        
        # Raw CDC format (less common)
        raise ValueError(f"Unsupported CDC message format: {type(payload)}")
    
    async def _commit_cdc_offset(self, message: Any) -> None:
        """Commit CDC consumer offset after successful processing."""
        if hasattr(self.cdc_consumer, 'commit'):
            await self.cdc_consumer.commit()
```

### Configuration Changes

Add mode configuration to `OutboxConfig`:

```python
@dataclass
class OutboxConfig:
    """Configuration for the outbox pattern."""
    
    # Existing fields...
    batch_size: int = 100
    poll_interval_seconds: float = 1.0
    claim_timeout_seconds: float = 300.0
    max_retries: int = 10
    
    # NEW: Worker mode
    mode: WorkerMode = WorkerMode.POLLING
    
    # NEW: CDC-specific config
    cdc_consumer_group: str = "sagaz-outbox-workers"
    cdc_stream_name: str = "saga.outbox.events"
    
    @classmethod
    def from_env(cls) -> "OutboxConfig":
        """Create config from environment variables."""
        import os
        
        # Parse mode from environment
        mode_str = os.getenv("SAGAZ_OUTBOX_MODE", "polling").lower()
        mode = WorkerMode.CDC if mode_str == "cdc" else WorkerMode.POLLING
        
        return cls(
            batch_size=int(os.getenv("OUTBOX_BATCH_SIZE", 100)),
            poll_interval_seconds=float(os.getenv("OUTBOX_POLL_INTERVAL", 1.0)),
            claim_timeout_seconds=float(os.getenv("OUTBOX_CLAIM_TIMEOUT", 300.0)),
            max_retries=int(os.getenv("OUTBOX_MAX_RETRIES", 10)),
            mode=mode,
            cdc_consumer_group=os.getenv("OUTBOX_CONSUMER_GROUP", "sagaz-outbox-workers"),
            cdc_stream_name=os.getenv("OUTBOX_STREAM_NAME", "saga.outbox.events"),
        )
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

## Migration Path (Using Unified Worker)

### Stage 1: Parallel Running (Both Modes)

```
                     ┌─────────────────┐
                     │   saga_outbox   │
                     └────────┬────────┘
                              │
               ┌──────────────┼──────────────┐
               │              │              │
               ▼              ▼              ▼
         ┌──────────┐  ┌──────────────┐  ┌─────────────┐
         │ Worker   │  │ CDC Capture  │  │  Worker     │
         │ (polling)│  │  (Debezium)  │  │  (cdc mode) │
         │ mode     │  │              │  │             │
         └──────────┘  └──────────────┘  └─────────────┘
                              │              │
                              └──────────────┘
                               Both publish to
                               same broker topic
```

**Deployment example:**

```yaml
# Polling workers (existing)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: outbox-worker-polling
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: worker
          image: sagaz/outbox-worker:latest
          env:
            - name: SAGAZ_OUTBOX_MODE
              value: "polling"  # <-- Polling mode
            - name: BATCH_SIZE
              value: "100"

---
# CDC workers (new)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: outbox-worker-cdc
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: worker
          image: sagaz/outbox-worker:latest
          env:
            - name: SAGAZ_OUTBOX_MODE
              value: "cdc"  # <-- CDC mode
            - name: OUTBOX_STREAM_NAME
              value: "saga.outbox.events"
            - name: OUTBOX_CONSUMER_GROUP
              value: "sagaz-outbox-workers"
```

### Stage 2: Cutover

1. Verify CDC workers are processing (check metrics)
2. Gradually scale down polling workers: `kubectl scale deployment/outbox-worker-polling --replicas=0`
3. Monitor CDC throughput and lag

### Stage 3: Cleanup

1. Remove polling worker deployment
2. Optionally remove `status` column (if not needed for debugging)
3. Update monitoring dashboards

### Environment Variable Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `SAGAZ_OUTBOX_MODE` | `polling` | Worker mode: `polling` or `cdc` |
| `OUTBOX_STREAM_NAME` | `saga.outbox.events` | CDC stream/topic name (CDC mode only) |
| `OUTBOX_CONSUMER_GROUP` | `sagaz-outbox-workers` | Consumer group ID (CDC mode only) |
| `BATCH_SIZE` | `100` | Batch size (polling mode only) |
| `POLL_INTERVAL` | `1.0` | Poll interval seconds (polling mode only) |

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

## Implementation Phases (Updated for Unified Worker)

| Phase | Scope | Effort |
|-------|-------|--------|
| 1. Design & ADR | This document | ✅ Done |
| 2. Schema prep | Publication, replication slot | 2 hours |
| 3. Debezium config | Connector JSON, K8s deployment | 4 hours |
| 4. Extend OutboxWorker | Add CDC mode + WorkerMode enum | 6 hours |
| 5. CDC consumer factory | Create CDC consumer from config | 4 hours |
| 6. Testing | Integration tests, benchmarks | 8 hours |
| 7. Documentation | Migration guide, runbooks | 4 hours |

**Total estimate**: ~28 hours (3-4 days)

**Key changes from original plan:**
- ✅ No separate `CDCOutboxWorker` class - extend existing worker
- ✅ Single codebase with mode toggle
- ✅ Same deployment tooling, just change env vars
- ✅ Easier testing (same test harness for both modes)

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

**Implementation approach**: Extend existing `OutboxWorker` with `WorkerMode` enum (POLLING | CDC). Same worker class, same deployment process, just toggle `SAGAZ_OUTBOX_MODE` environment variable.

---

## See Also

- [Roadmap](../../ROADMAP.md#q2-2026) - Implementation timeline
- [ADR-012: Synchronous Orchestration](adr-012-synchronous-orchestration-model.md) - Current architecture
- [ADR-013: Fluss Analytics](adr-013-fluss-iceberg-analytics.md) - Analytics layer

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

---

## Usage Examples (Unified Worker)

### Polling Mode (Current/Default)

```python
from sagaz.outbox import OutboxWorker, WorkerMode
from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
from sagaz.outbox.brokers import KafkaBroker

storage = PostgreSQLOutboxStorage("postgresql://localhost/db")
broker = KafkaBroker(bootstrap_servers="localhost:9092")

await storage.initialize()
await broker.connect()

# Polling mode (default)
worker = OutboxWorker(
    storage=storage,
    broker=broker,
    mode=WorkerMode.POLLING  # <-- Polling mode
)

await worker.start()  # Polls database every 1 second
```

### CDC Mode (High Throughput)

```python
from sagaz.outbox import OutboxWorker, WorkerMode
from sagaz.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
from sagaz.outbox.brokers import KafkaBroker
from aiokafka import AIOKafkaConsumer

storage = PostgreSQLOutboxStorage("postgresql://localhost/db")
broker = KafkaBroker(bootstrap_servers="localhost:9092")

# Create CDC consumer (Kafka)
cdc_consumer = AIOKafkaConsumer(
    'saga.outbox.events',  # Debezium output topic
    bootstrap_servers='localhost:9092',
    group_id='sagaz-outbox-workers',
    auto_offset_reset='earliest'
)

await storage.initialize()  # Still needed for metrics
await broker.connect()
await cdc_consumer.start()

# CDC mode
worker = OutboxWorker(
    storage=storage,
    broker=broker,
    mode=WorkerMode.CDC,  # <-- CDC mode
    cdc_consumer=cdc_consumer  # <-- CDC consumer required
)

await worker.start()  # Consumes from CDC stream
```

### Configuration from Environment

```python
from sagaz.outbox import OutboxWorker, OutboxConfig
from sagaz.outbox.factory import create_worker_from_env

# Reads SAGAZ_OUTBOX_MODE, OUTBOX_STREAM_NAME, etc.
config = OutboxConfig.from_env()
worker = await create_worker_from_env(config)

await worker.start()
```

**Environment variables:**
```bash
# Polling mode
export SAGAZ_OUTBOX_MODE=polling
export BATCH_SIZE=100
export POLL_INTERVAL=1.0

# CDC mode
export SAGAZ_OUTBOX_MODE=cdc
export OUTBOX_STREAM_NAME=saga.outbox.events
export OUTBOX_CONSUMER_GROUP=sagaz-outbox-workers
export BROKER_TYPE=kafka
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```


---

## CLI Integration

CDC should be integrated into the project initialization and extension workflow for seamless setup.

### `sagaz init` - New Project Setup

When initializing a new project, users can choose CDC mode:

```bash
# Interactive wizard
$ sagaz init
? Select outbox mode:
  > Polling (default, simple)
    CDC (high-throughput, requires Debezium)

# Or via flags
$ sagaz init --local --outbox-mode=polling
$ sagaz init --local --outbox-mode=cdc --outbox-broker=kafka
$ sagaz init --k8s --outbox-mode=cdc --outbox-broker=redis
```

**Generated files (polling mode):**
```
myproject/
├── docker-compose.yml          # PostgreSQL + RabbitMQ/Kafka
├── .env
│   SAGAZ_OUTBOX_MODE=polling
│   BATCH_SIZE=100
└── k8s/
    └── outbox-worker.yaml      # Polling worker deployment
```

**Generated files (CDC mode):**
```
myproject/
├── docker-compose.yml          # PostgreSQL + Debezium + Broker
├── debezium/
│   └── application.properties  # Debezium Server config
├── .env
│   SAGAZ_OUTBOX_MODE=cdc
│   OUTBOX_STREAM_NAME=saga.outbox.events
└── k8s/
    ├── debezium-server.yaml    # Debezium Server deployment
    └── outbox-worker.yaml      # CDC worker deployment
```

### `sagaz extend` - Upgrade Existing Project

Enable CDC on an existing project without breaking changes:

```bash
# Extend existing project with CDC
$ sagaz extend --enable-outbox-cdc

? Select CDC broker:
  > Kafka
    Redis Streams
    RabbitMQ

? Run in hybrid mode (parallel polling + CDC)?
  > Yes (recommended for migration)
    No (CDC only)

✓ Generated debezium/application.properties
✓ Updated docker-compose.yml (added Debezium service)
✓ Generated k8s/debezium-server.yaml
✓ Generated k8s/outbox-worker-cdc.yaml
✓ Updated .env (added CDC variables)

Next steps:
  1. Review generated files
  2. Start Debezium: docker-compose up debezium-server
  3. Deploy CDC workers: kubectl apply -f k8s/outbox-worker-cdc.yaml
  4. Monitor metrics: kubectl port-forward svc/prometheus 9090
  5. Scale down polling workers when ready
```

### CLI Commands

#### `sagaz init`

```bash
sagaz init [OPTIONS]

Options:
  --local              Generate Docker Compose setup (default)
  --k8s                Generate Kubernetes manifests
  --outbox-mode TEXT      Outbox mode: polling|cdc (default: polling)
  --outbox-broker TEXT    CDC broker: kafka|redis|rabbitmq (required if cdc-mode=cdc)
  --hybrid             Enable hybrid mode (polling + CDC)
  --help               Show this message and exit

Examples:
  sagaz init --local
  sagaz init --local --outbox-mode=cdc --outbox-broker=kafka
  sagaz init --k8s --outbox-mode=cdc --outbox-broker=redis --hybrid
```

#### `sagaz extend`

```bash
sagaz extend [OPTIONS]

Options:
  --enable-outbox-cdc         Enable CDC on existing project
  --outbox-broker TEXT    CDC broker: kafka|redis|rabbitmq
  --hybrid             Run in hybrid mode (recommended)
  --no-backup          Skip backing up existing files
  --help               Show this message and exit

Examples:
  sagaz extend --enable-outbox-cdc --outbox-broker=kafka --hybrid
  sagaz extend --enable-outbox-cdc --outbox-broker=redis
```

#### `sagaz status`

Show current outbox mode and health:

```bash
$ sagaz status

Sagaz Project Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Outbox Mode:       CDC (Kafka)
Workers:           3 polling, 5 cdc (hybrid mode)
Debezium:          ✓ Running (1 replica)
CDC Lag:           12ms
Pending Events:    47
Throughput:        12,500 events/sec
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Services:
  ✓ PostgreSQL        localhost:5432
  ✓ Kafka             localhost:9092
  ✓ Debezium Server   Running
  ✓ Outbox Workers    8 running (3 polling, 5 cdc)
  ✓ Prometheus        localhost:9090

Run 'sagaz logs' to view worker logs
```

### Template Structure

```
sagaz/templates/
├── init/
│   ├── polling/
│   │   ├── docker-compose.yml.j2
│   │   ├── .env.j2
│   │   └── k8s/
│   │       └── outbox-worker.yaml.j2
│   └── cdc/
│       ├── docker-compose.yml.j2          # Includes Debezium
│       ├── debezium/
│       │   ├── kafka.properties.j2
│       │   ├── redis.properties.j2
│       │   └── rabbitmq.properties.j2
│       ├── .env.j2
│       └── k8s/
│           ├── debezium-server.yaml.j2
│           └── outbox-worker.yaml.j2
└── extend/
    └── cdc/
        ├── debezium-patch.yml.j2          # Patch for docker-compose
        ├── debezium/
        │   └── application.properties.j2
        └── k8s/
            ├── debezium-server.yaml.j2
            └── outbox-worker-cdc.yaml.j2
```

### Environment Variable Presets

The CLI should generate appropriate presets:

**Polling mode:**
```env
# Outbox Configuration
SAGAZ_OUTBOX_MODE=polling
BATCH_SIZE=100
POLL_INTERVAL=1.0
MAX_RETRIES=10

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/saga_db

# Broker
BROKER_TYPE=kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

**CDC mode:**
```env
# Outbox Configuration
SAGAZ_OUTBOX_MODE=cdc
OUTBOX_STREAM_NAME=saga.outbox.events
OUTBOX_CONSUMER_GROUP=sagaz-outbox-workers
MAX_RETRIES=10

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/saga_db

# Broker (for publishing)
BROKER_TYPE=kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Debezium (separate service)
DEBEZIUM_ENABLED=true
```

### Docker Compose Integration

#### Polling Mode

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: saga_db
    ports:
      - "5432:5432"

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    ports:
      - "9092:9092"

  outbox-worker:
    image: sagaz/outbox-worker:latest
    environment:
      SAGAZ_OUTBOX_MODE: polling
      BATCH_SIZE: 100
      DATABASE_URL: postgresql://postgres@postgres:5432/saga_db
      BROKER_TYPE: kafka
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
    depends_on:
      - postgres
      - kafka
```

#### CDC Mode

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: saga_db
    ports:
      - "5432:5432"
    command:
      - "postgres"
      - "-c"
      - "wal_level=logical"  # CDC requirement

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    ports:
      - "9092:9092"

  debezium-server:
    image: quay.io/debezium/server:2.4
    volumes:
      - ./debezium:/debezium/conf
    environment:
      QUARKUS_LOG_LEVEL: INFO
    depends_on:
      - postgres
      - kafka

  outbox-worker:
    image: sagaz/outbox-worker:latest
    environment:
      SAGAZ_OUTBOX_MODE: cdc
      OUTBOX_STREAM_NAME: saga.outbox.events
      OUTBOX_CONSUMER_GROUP: sagaz-outbox-workers
      DATABASE_URL: postgresql://postgres@postgres:5432/saga_db
      BROKER_TYPE: kafka
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
    depends_on:
      - debezium-server
```

### Migration Workflow

The CLI should guide users through migration:

```bash
$ sagaz extend --enable-outbox-cdc --outbox-broker=kafka

✓ Detected existing polling mode setup
✓ Backed up configuration to .sagaz-backup/

Migration Plan:
  1. Add Debezium Server to docker-compose.yml
  2. Generate Debezium configuration (debezium/kafka.properties)
  3. Create CDC worker deployment (k8s/outbox-worker-cdc.yaml)
  4. Run in hybrid mode (both polling + CDC workers)

? Proceed with migration? [Y/n]: y

✓ Generated files
✓ Updated docker-compose.yml

Next steps:
  1. Review generated files
  2. Start Debezium:
     $ docker-compose up -d debezium-server
  
  3. Verify CDC is working:
     $ sagaz status
  
  4. When ready, scale down polling workers:
     $ docker-compose scale outbox-worker-polling=0
     OR
     $ kubectl scale deployment/outbox-worker-polling --replicas=0
  
  5. Remove polling workers when CDC is stable:
     $ sagaz extend --remove-polling

For detailed migration guide, see:
  docs/guides/cdc-migration.md
```

### Configuration Validation

```bash
$ sagaz validate

Validating Sagaz Configuration...

✓ PostgreSQL connection: OK
✓ Kafka broker: OK
✓ Debezium Server: OK
✗ CDC lag too high: 5000ms (threshold: 1000ms)
⚠ Polling workers still running (consider scaling down)

Recommendations:
  - Scale up CDC workers: kubectl scale deployment/outbox-worker-cdc --replicas=10
  - Check Debezium logs: docker-compose logs debezium-server
```

---

## Implementation Tasks for CLI Integration

| Task | Effort | Priority |
|------|--------|----------|
| Add `--outbox-mode` flag to `sagaz init` | 2 hours | High |
| Create CDC templates (Debezium configs) | 4 hours | High |
| Implement `sagaz extend --enable-outbox-cdc` | 6 hours | High |
| Add CDC status to `sagaz status` | 3 hours | Medium |
| Create migration workflow | 4 hours | High |
| Add `sagaz validate` CDC checks | 3 hours | Medium |
| Write CLI integration tests | 4 hours | Medium |
| Update documentation | 2 hours | High |

**Total**: ~28 hours

---

## CLI Integration Benefits

| Benefit | Description |
|---------|-------------|
| ✅ **Turnkey setup** | `sagaz init --outbox-mode=cdc` generates everything |
| ✅ **Zero manual config** | No need to write Debezium configs by hand |
| ✅ **Safe migration** | `--hybrid` mode allows gradual cutover |
| ✅ **Validation** | `sagaz validate` checks CDC health |
| ✅ **Guided workflow** | CLI prompts guide users through setup |
| ✅ **Backup safety** | Auto-backup before extending |

