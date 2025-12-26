# Components & Service Artifacts

This document details the core classes, modules, and their responsibilities.

## Module Structure

```
sagaz/
├── __init__.py              # Public API exports
├── core.py                  # Saga engine (793 lines)
├── context.py               # SagaContext implementation
├── orchestrator.py          # SagaOrchestrator
├── types.py                 # Enums, dataclasses
├── exceptions.py            # Custom exceptions
├── compensation_graph.py    # Parallel compensation DAG
│
└── outbox/                  # Transactional outbox
    ├── __init__.py
    ├── worker.py            # OutboxWorker
    ├── types.py             # OutboxEvent, OutboxConfig
    ├── state_machine.py     # Event state transitions
    │
    ├── storage/             # Storage backends
    │   ├── base.py          # Abstract OutboxStorage
    │   ├── postgresql.py    # PostgreSQL implementation
    │   └── memory.py        # In-memory (testing)
    │
    └── brokers/             # Message brokers
        ├── base.py          # Abstract MessageBroker
        ├── kafka.py         # Kafka implementation
        ├── rabbitmq.py      # RabbitMQ implementation
        └── memory.py        # In-memory (testing)
```

---

## Core Components

### Saga

The main entry point for defining sagas using a fluent builder API.

```python
from sagaz import Saga

saga = (
    Saga("order-processing")
    .step("reserve_inventory")
        .action(reserve_inventory)
        .compensation(release_inventory)
    .step("charge_payment")
        .action(charge_payment)
        .compensation(refund_payment)
    .step("ship_order")
        .action(ship_order)
        .compensation(cancel_shipment)
    .build()
)

result = await saga.execute(context)
```

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Saga identifier |
| `steps` | `List[SagaStep]` | Ordered execution steps |
| `timeout` | `float` | Maximum execution time |
| `max_retries` | `int` | Retry attempts per step |

### SagaStep

Represents a single step with action and optional compensation.

```python
@dataclass
class SagaStep:
    name: str
    action: Callable[[SagaContext], Awaitable[Any]]
    compensation: Optional[Callable[[SagaContext], Awaitable[None]]]
    timeout: Optional[float] = None
    retries: int = 0
```

### SagaContext

Thread-safe shared state container passed to all steps.

```python
class SagaContext:
    saga_id: str
    data: Dict[str, Any]      # Mutable shared state
    metadata: Dict[str, Any]  # Read-only metadata
    
    def set(self, key: str, value: Any) -> None
    def get(self, key: str, default: Any = None) -> Any
```

---

## Outbox Components

### OutboxEvent

Represents an event stored in the outbox table.

```python
@dataclass
class OutboxEvent:
    event_id: UUID
    saga_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Dict[str, Any]
    headers: Dict[str, Any]
    status: OutboxStatus
    created_at: datetime
    sent_at: Optional[datetime]
    retry_count: int
    last_error: Optional[str]
```

### OutboxStatus

State machine for event lifecycle.

```
                    ┌─────────────┐
                    │   PENDING   │ ◄─── Initial state
                    └──────┬──────┘
                           │
                    claim_batch()
                           │
                    ┌──────▼──────┐
              ┌─────│   CLAIMED   │─────┐
              │     └─────────────┘     │
              │                         │
        publish_ok()              publish_fail()
              │                         │
       ┌──────▼──────┐          ┌──────▼──────┐
       │    SENT     │          │   FAILED    │
       └─────────────┘          └──────┬──────┘
                                       │
                              retry_count >= max?
                                       │
                               ┌───────▼───────┐
                               │  DEAD_LETTER  │
                               └───────────────┘
```

### OutboxWorker

Background processor that publishes events to the message broker.

```python
class OutboxWorker:
    def __init__(
        self,
        storage: OutboxStorage,
        broker: MessageBroker,
        config: OutboxConfig,
        worker_id: Optional[str] = None,
    ): ...
    
    async def start(self) -> None:
        """Run continuous processing loop."""
    
    async def stop(self) -> None:
        """Graceful shutdown."""
    
    async def process_batch(self) -> int:
        """Process one batch of events."""
```

**Processing Loop:**

```python
while running:
    # 1. Claim batch with SKIP LOCKED
    events = await storage.claim_batch(worker_id, batch_size)
    
    # 2. Publish each event
    for event in events:
        await broker.publish_event(event)
        await storage.mark_sent(event.event_id)
    
    # 3. Sleep if no events
    if not events:
        await asyncio.sleep(poll_interval)
```

---

## Storage Backends

### OutboxStorage (Abstract)

```python
class OutboxStorage(ABC):
    @abstractmethod
    async def save_event(self, event: OutboxEvent) -> None: ...
    
    @abstractmethod
    async def claim_batch(
        self, 
        worker_id: str, 
        batch_size: int
    ) -> List[OutboxEvent]: ...
    
    @abstractmethod
    async def update_status(
        self, 
        event_id: UUID, 
        status: OutboxStatus,
        error_message: Optional[str] = None
    ) -> OutboxEvent: ...
```

### PostgreSQL Implementation

Uses `FOR UPDATE SKIP LOCKED` for safe concurrent access:

```sql
-- Claim batch of pending events
UPDATE saga_outbox
SET status = 'claimed', 
    worker_id = $1,
    claimed_at = NOW()
WHERE event_id IN (
    SELECT event_id FROM saga_outbox
    WHERE status = 'pending'
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

---

## Broker Backends

### MessageBroker (Abstract)

```python
class MessageBroker(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    
    @abstractmethod
    async def publish_event(self, event: OutboxEvent) -> None: ...
    
    @abstractmethod
    async def close(self) -> None: ...
```

### RabbitMQ Implementation

- Uses `aio-pika` for async operations
- Publishes to exchange with routing key = `event_type`
- Supports publisher confirms

### Kafka Implementation

- Uses `aiokafka` for async operations
- Partitions by `saga_id` for ordering
- Supports idempotent producer

---

## Compensation Graph

For complex sagas with parallel steps and dependencies.

```python
from sagaz import CompensationGraph

graph = CompensationGraph()
graph.add_node("payment", compensate_payment)
graph.add_node("inventory", compensate_inventory)
graph.add_node("shipping", compensate_shipping, depends_on=["payment"])

# Executes: payment & inventory (parallel), then shipping
await graph.execute_compensations(context)
```

---

## Database Schema

### saga_outbox

```sql
CREATE TABLE saga_outbox (
    event_id        UUID PRIMARY KEY,
    saga_id         VARCHAR(255) NOT NULL,
    aggregate_type  VARCHAR(255) NOT NULL,
    aggregate_id    VARCHAR(255) NOT NULL,
    event_type      VARCHAR(255) NOT NULL,
    payload         JSONB NOT NULL,
    headers         JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at      TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    worker_id       VARCHAR(255)
);

-- Performance indexes
CREATE INDEX idx_outbox_pending ON saga_outbox (created_at) 
    WHERE status = 'pending';
CREATE INDEX idx_outbox_saga_id ON saga_outbox (saga_id);
```

### consumer_inbox

```sql
CREATE TABLE consumer_inbox (
    event_id        UUID PRIMARY KEY,
    consumer_name   VARCHAR(255) NOT NULL,
    source_topic    VARCHAR(255) NOT NULL,
    event_type      VARCHAR(255) NOT NULL,
    payload         JSONB NOT NULL,
    consumed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Next Steps

- [Dataflow](dataflow.md) - Event flow through the system
- [Architecture Decisions](decisions.md) - Why we made these choices
