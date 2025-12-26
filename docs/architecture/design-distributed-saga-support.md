# Design Document: Distributed Saga Support (v2.0)

> **Status**: Draft - Future Feature  
> **Author**: Sagaz Team  
> **Created**: 2025-12-26  
> **Target Version**: Sagaz 2.0

---

## Executive Summary

This document outlines the design for extending Sagaz to support **distributed saga orchestration**, where saga steps execute as separate microservices communicating via message broker. This would complement the existing synchronous orchestration model for use cases requiring true microservice boundaries.

---

## Motivation

### Current Limitation

Sagaz v1.0 implements synchronous orchestration where all saga steps execute within a single Python process:

```python
# Current: Steps are direct function calls
class OrderSaga(Saga):
    @action("reserve_inventory")
    async def reserve_inventory(self, ctx):
        return await self.inventory_service.reserve(ctx["items"])  # Direct call
```

### When Distributed is Needed

| Scenario | Why Distributed? |
|----------|------------------|
| **Multi-language services** | Inventory service is in Go, Payments in Java |
| **Independent scaling** | Payment step needs 10x more instances than order creation |
| **Failure isolation** | Don't want inventory service crash to kill order service |
| **Team boundaries** | Different teams own different services |
| **Regulatory compliance** | Payment processing must be in separate PCI-compliant service |

---

## Proposed Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           SAGA ORCHESTRATOR SERVICE                        │
│                                                                            │
│  ┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐ │
│  │                   │     │                   │     │                   │ │
│  │  DistributedSaga  │     │   SagaStateStore  │     │  ReplyConsumer    │ │
│  │                   │     │   (PostgreSQL)    │     │  (listens for     │ │
│  │  - start()        │────►│                   │◄────│   step replies)   │ │
│  │  - resume()       │     │  - saga_state     │     │                   │ │
│  │  - compensate()   │     │  - step_status    │     └─────────┬─────────┘ │
│  │                   │     │  - correlation_id │               │           │
│  └─────────┬─────────┘     └───────────────────┘               │           │
│            │                                                   │           │
│            ▼                                                   │           │
│  ┌───────────────────┐                                         │           │
│  │   Command Outbox   │                                        │           │
│  │   (saga_commands)  │                                        │           │
│  └─────────┬─────────┘                                         │           │
└────────────┼───────────────────────────────────────────────────┼───────────┘
             │                                                   │
             ▼                                                   │
┌────────────────────────────────────────────────────────────────┴───────────┐
│                              MESSAGE BROKER                                │
│                                                                            │
│   ┌────────────────────┐              ┌─────────────────────────────────┐  │
│   │  Commands Topics   │              │      Reply Topics               │  │
│   │  {service}.commands│              │  saga.replies.{saga_name}       │  │
│   │                    │              │  (partitioned by saga_id)       │  │
│   └─────────┬──────────┘              └──────────────▲──────────────────┘  │
│             │                                        │                     │
└─────────────┼────────────────────────────────────────┼─────────────────────┘
              │                                        │
              ▼                                        │
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PARTICIPANT SERVICES                               │
│                                                                             │
│  ┌──────────────────────────┐    ┌──────────────────────────┐               │
│  │   Inventory Service      │    │   Payment Service        │               │
│  │                          │    │                          │               │
│  │  ┌─────────────────────┐ │    │  ┌─────────────────────┐ │               │
│  │  │  CommandConsumer    │ │    │  │  CommandConsumer    │ │               │
│  │  │  (SagaParticipant)  │ │    │  │  (SagaParticipant)  │ │               │
│  │  └──────────┬──────────┘ │    │  └──────────┬──────────┘ │               │
│  │             │            │    │             │            │               │
│  │             ▼            │    │             ▼            │               │
│  │  ┌─────────────────────┐ │    │  ┌─────────────────────┐ │               │
│  │  │  Business Logic     │ │    │  │  Business Logic     │ │               │
│  │  │  reserve_inventory()│ │    │  │  charge_payment()   │ │               │
│  │  └──────────┬──────────┘ │    │  └──────────┬──────────┘ │               │
│  │             │            │    │             │            │               │
│  │             ▼            │    │             ▼            │               │
│  │  ┌─────────────────────┐ │    │  ┌─────────────────────┐ │               │
│  │  │    Reply Outbox     │ │    │  │    Reply Outbox     │ │               │
│  │  └─────────────────────┘ │    │  └─────────────────────┘ │               │
│  └──────────────────────────┘    └──────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Topic Organization Strategy

A critical design decision is how to organize broker topics for commands and replies.

### Topic Structure Options

| Strategy | Commands | Replies | Pros | Cons |
|----------|----------|---------|------|------|
| **Single shared** | `saga.commands` | `saga.replies` | Simple | All mixed, hard to scale |
| **Per-service** | `{service}.commands` | `saga.replies` | Decoupled commands | Replies still mixed |
| **Per-saga-type** | `{service}.commands` | `saga.replies.{saga_name}` | ✅ Isolated, scalable | More topics |
| **Per-saga-instance** | N/A | `saga.replies.{saga_id}` | Perfect isolation | Topic explosion ❌ |

### Recommended: Per-Saga-Type Reply Topics with Partitioning

```
Commands:  {service}.commands         (e.g., inventory.commands, payment.commands)
Replies:   saga.replies.{saga_name}   (e.g., saga.replies.order_saga)
           └── partitioned by saga_id for ordering
```

**Benefits:**

1. **Isolation by saga type** - Order saga replies don't mix with Payment saga replies
2. **Ordering guarantee** - All replies for a single saga instance go to the same partition
3. **Independent scaling** - Can add more consumers for high-volume saga types
4. **No topic explosion** - Fixed number of topics (one per saga type, not per instance)
5. **Avoid cross-lagging** - Slow sagas of one type don't block others

**Partition Key Strategy:**

```python
# When publishing a reply
await producer.send(
    topic=f"saga.replies.{command.saga_name}",
    key=command.saga_id,  # Partition key ensures ordering
    value=reply.to_json(),
)
```

**Consumer Group per Saga Type:**

```python
# Each saga type has its own consumer group
order_saga_consumer = KafkaConsumer(
    topic="saga.replies.order_saga",
    group_id="order-saga-orchestrator",
)

payment_saga_consumer = KafkaConsumer(
    topic="saga.replies.payment_saga",
    group_id="payment-saga-orchestrator",
)
```

### Visual: Topic Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MESSAGE BROKER                                 │
│                                                                             │
│  COMMAND TOPICS (per service)         REPLY TOPICS (per saga type)          │
│  ┌─────────────────────┐              ┌─────────────────────────────────┐   │
│  │ inventory.commands  │              │ saga.replies.order_saga         │   │
│  ├─────────────────────┤              │   ├─ partition 0 (saga_id % N)  │   │
│  │ payment.commands    │              │   ├─ partition 1                │   │
│  ├─────────────────────┤              │   └─ partition 2                │   │
│  │ shipping.commands   │              ├─────────────────────────────────┤   │
│  └─────────────────────┘              │ saga.replies.payment_saga       │   │
│                                       │   ├─ partition 0                │   │
│                                       │   └─ partition 1                │   │
│                                       └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Theoretical Foundation

Distributed sagas are fundamentally a **distributed systems coordination problem**. The design draws heavily on Leslie Lamport's foundational work on distributed systems.

### Mapping Lamport's Concepts to Sagas

| Concept | Lamport's Work | Saga Application |
|---------|----------------|------------------|
| **Event Ordering** | Happened-Before (→) relation | Step N → Reply N → Step N+1 |
| **Logical Clocks** | Lamport Timestamps | `current_step_index`, `correlation_id` |
| **State Machines** | State Machine Replication | Saga status transitions (PENDING → EXECUTING → ...) |
| **Fault Tolerance** | Crash recovery via logs | `SagaStateStore` persistence |
| **Message Ordering** | Total order within channels | Partitioning by `saga_id` |

### Happened-Before Relation (→)

Lamport's partial ordering of events is the foundation of our saga flow:

```
Command(Step1) → Reply(Step1) → Command(Step2) → Reply(Step2) → ...
       │              │              │              │
       └──────────────┴──────────────┴──────────────┘
                    Causal chain (happened-before)
```

The `correlation_id` and sequential step execution establish this causal chain. A step N+1 command is only sent *after* step N's reply is received, enforcing the happened-before constraint.

### Logical Clocks and Saga Progress

While we don't explicitly use Lamport timestamps, the saga state serves a similar purpose:

```python
@dataclass
class SagaState:
    current_step_index: int      # Logical clock for saga progress
    completed_steps: list[str]   # Causal history (what happened before "now")
    correlation_id: str          # Links command → reply (causal edge)
```

**Potential Enhancement:** Adding explicit Lamport timestamps would enable:
- Detecting stale/out-of-order replies across partitions
- Enhanced distributed tracing correlation
- Debugging timing issues in complex multi-saga scenarios

### State Machine Replication

The saga orchestrator **is** a replicated state machine:

```
                    reply(success)
     ┌─────────────────────────────────────────┐
     │                                         │
     ▼          start()         reply(ok)      │    all steps done
┌─────────┐   ─────────►   ┌───────────┐   ────┴────►   ┌───────────┐
│ PENDING │                │ EXECUTING │               │ COMPLETED │
└─────────┘                └─────┬─────┘               └───────────┘
                                 │
                          reply(failure)
                                 │
                                 ▼
                         ┌──────────────┐    all compensated    ┌─────────────┐
                         │ COMPENSATING │  ────────────────────►│ ROLLED_BACK │
                         └──────┬───────┘                       └─────────────┘
                                │
                         compensation failed
                                │
                                ▼
                           ┌────────┐
                           │ FAILED │
                           └────────┘
```

Lamport's insight: If all replicas process the same commands in the same order, they reach the same state. Our `SagaStateStore` persistence enables:
- **Recovery**: Replay from persisted state after crash
- **Consistency**: Single source of truth for saga progress
- **Idempotency**: Inbox pattern prevents duplicate processing

### Message Ordering via Partitioning

Lamport proved that messages from the same source to the same destination can be totally ordered. We apply this via Kafka partitioning:

```
saga_id = "order-123"  →  hash(saga_id) % num_partitions  →  partition 2

All messages for order-123 go to partition 2, ensuring FIFO ordering.
```

This is why the per-saga-type reply topics with `saga_id` partitioning work:
- Within a partition: **Total order** (FIFO)
- Across partitions: **Partial order** (no guarantee, but not needed)

### Exactly-Once Semantics

Lamport's work on fault tolerance informs our approach:

| Challenge | Solution | Lamport Connection |
|-----------|----------|-------------------|
| Message loss | At-least-once delivery (broker retries) | Reliable broadcast |
| Duplicate messages | Inbox pattern (idempotency) | Unique message IDs |
| Process crash | State persistence + recovery | Stable storage requirement |

The combination gives us **exactly-once semantics** (or more precisely, "effectively-once"):
```
At-least-once delivery + Idempotent processing = Exactly-once semantics
```

### What We Don't Need: Full Consensus

Interestingly, distributed sagas typically **don't** require full Paxos/Raft consensus because:

1. **Single orchestrator** - Only one process decides saga progression
2. **Crash failures only** - We assume services are honest (not Byzantine)
3. **Saga-local ordering** - We only need order within one saga, not global order

However, if **high availability** of the orchestrator is required, Raft-based leader election could be added (e.g., using etcd or PostgreSQL advisory locks).

### References

1. Lamport, L. (1978). **"Time, Clocks, and the Ordering of Events in a Distributed System"** - Defines happened-before, logical clocks
2. Lamport, L. (1984). **"Using Time Instead of Timeout for Fault-Tolerant Distributed Systems"** - Timeout-based failure detection
3. Schneider, F.B. (1990). **"Implementing Fault-Tolerant Services Using the State Machine Approach"** - State machine replication tutorial
4. Garcia-Molina, H. & Salem, K. (1987). **"Sagas"** - Original saga pattern paper

---

## Core Components

### 1. Command/Reply Message Protocol

#### SagaCommand

```python
@dataclass
class SagaCommand:
    """Command sent from orchestrator to participant."""
    
    # Correlation
    saga_id: str              # Unique saga instance ID
    saga_name: str            # Saga type name
    step_name: str            # Current step name
    correlation_id: str       # For reply matching
    
    # Routing
    participant_type: str     # Target service identifier
    action_type: str          # 'execute' or 'compensate'
    
    # Payload
    payload: dict[str, Any]   # Step-specific data
    
    # Metadata
    reply_topic: str          # Where to send response
    timeout_at: datetime      # When orchestrator will consider this timed out
    attempt: int              # Retry attempt number
    headers: dict[str, str]   # Tracing, auth, etc.
```

#### SagaReply

```python
@dataclass
class SagaReply:
    """Reply sent from participant back to orchestrator."""
    
    # Correlation
    saga_id: str
    correlation_id: str       # Matches command.correlation_id
    step_name: str
    
    # Result
    status: ReplyStatus       # SUCCESS, FAILURE, COMPENSATED
    result: dict[str, Any]    # Success payload
    error: Optional[ErrorInfo]  # Failure details
    
    # Metadata
    participant_id: str       # Which instance processed this
    processed_at: datetime
    headers: dict[str, str]
```

#### ReplyStatus Enum

```python
class ReplyStatus(Enum):
    SUCCESS = "success"           # Step completed successfully
    FAILURE = "failure"           # Step failed, needs compensation
    COMPENSATED = "compensated"   # Compensation completed
    COMPENSATION_FAILED = "compensation_failed"  # Compensation failed
```

---

### 2. DistributedSaga Class

The main orchestrator-side API for defining distributed sagas:

```python
class DistributedSaga:
    """
    Distributed saga orchestrator.
    
    Unlike the synchronous Saga class, steps are defined as remote commands
    rather than local function calls.
    
    Example:
        class OrderSaga(DistributedSaga):
            name = "order_saga"
            
            steps = [
                RemoteStep(
                    name="reserve_inventory",
                    participant="inventory-service",
                    command_topic="inventory.commands",
                    compensation_topic="inventory.commands",
                    timeout=30.0,
                ),
                RemoteStep(
                    name="charge_payment",
                    participant="payment-service",
                    command_topic="payment.commands",
                    compensation_topic="payment.commands",
                    timeout=60.0,
                ),
            ]
    """
    
    # Class-level attributes
    name: str  # e.g., "order_saga"
    
    def __init__(
        self,
        state_store: SagaStateStore,
        command_publisher: CommandPublisher,
    ):
        self.state_store = state_store
        self.command_publisher = command_publisher
    
    @property
    def reply_topic(self) -> str:
        """Reply topic derived from saga name for isolation."""
        return f"saga.replies.{self.name}"
    
    async def start(self, initial_data: dict[str, Any]) -> str:
        """
        Start a new saga instance.
        
        Returns saga_id for tracking.
        """
        saga_id = str(uuid.uuid4())
        
        # Persist initial state
        await self.state_store.create_saga(
            saga_id=saga_id,
            saga_name=self.name,
            status=SagaStatus.PENDING,
            context=initial_data,
            current_step_index=0,
        )
        
        # Send first command
        await self._send_next_command(saga_id)
        
        return saga_id
    
    async def on_reply(self, reply: SagaReply):
        """
        Handle a reply from a participant.
        
        Called by ReplyConsumer when a message arrives.
        """
        saga_state = await self.state_store.get_saga(reply.saga_id)
        
        if reply.status == ReplyStatus.SUCCESS:
            await self._handle_success(saga_state, reply)
        elif reply.status == ReplyStatus.FAILURE:
            await self._handle_failure(saga_state, reply)
        elif reply.status == ReplyStatus.COMPENSATED:
            await self._handle_compensated(saga_state, reply)
        elif reply.status == ReplyStatus.COMPENSATION_FAILED:
            await self._handle_compensation_failed(saga_state, reply)
    
    async def _handle_success(self, saga_state, reply):
        """Proceed to next step or complete saga."""
        # Update context with step result
        saga_state.context.update(reply.result)
        saga_state.completed_steps.append(reply.step_name)
        
        if saga_state.current_step_index + 1 >= len(self.steps):
            # All steps complete
            saga_state.status = SagaStatus.COMPLETED
            await self.state_store.update_saga(saga_state)
        else:
            # Proceed to next step
            saga_state.current_step_index += 1
            await self.state_store.update_saga(saga_state)
            await self._send_next_command(saga_state.saga_id)
    
    async def _handle_failure(self, saga_state, reply):
        """Start compensation."""
        saga_state.status = SagaStatus.COMPENSATING
        saga_state.failure_reason = reply.error
        await self.state_store.update_saga(saga_state)
        await self._send_compensation_command(saga_state)
```

---

### 3. RemoteStep Definition

```python
@dataclass
class RemoteStep:
    """
    Definition of a remote saga step.
    
    Unlike SagaStep (which holds callable functions), RemoteStep defines
    how to communicate with a remote participant.
    """
    
    name: str                    # Step identifier
    participant: str             # Target service name
    command_topic: str           # Broker topic for commands
    
    # Optional
    compensation_topic: Optional[str] = None  # Defaults to command_topic
    timeout: float = 30.0        # Seconds to wait for reply
    max_retries: int = 3         # Retry attempts on timeout
    
    # Payload transformation (optional)
    build_command: Optional[Callable[[dict], dict]] = None
    build_compensation: Optional[Callable[[dict], dict]] = None
```

---

### 4. SagaParticipant Base Class

For participant services to implement:

```python
class SagaParticipant(ABC):
    """
    Base class for saga participant services.
    
    Implement this in each microservice that participates in distributed sagas.
    
    Example:
        class InventoryParticipant(SagaParticipant):
            participant_type = "inventory-service"
            
            async def execute(self, command: SagaCommand) -> SagaReply:
                items = command.payload["items"]
                reservation_id = await self.inventory_service.reserve(items)
                return self.success_reply(command, {"reservation_id": reservation_id})
            
            async def compensate(self, command: SagaCommand) -> SagaReply:
                reservation_id = command.payload["reservation_id"]
                await self.inventory_service.release(reservation_id)
                return self.compensated_reply(command)
    """
    
    participant_type: str  # Unique identifier for this service
    
    def __init__(
        self,
        inbox_storage: InboxStorage,
        reply_publisher: ReplyPublisher,
    ):
        self.inbox = inbox_storage
        self.reply_publisher = reply_publisher
    
    async def process_command(self, command: SagaCommand):
        """
        Process an incoming command with idempotency.
        
        Called by the message consumer.
        """
        # Idempotency check
        if await self.inbox.exists(command.correlation_id):
            logger.info(f"Duplicate command {command.correlation_id}, skipping")
            return
        
        try:
            if command.action_type == "execute":
                reply = await self.execute(command)
            else:
                reply = await self.compensate(command)
            
            # Mark as processed and send reply in single transaction
            async with self.inbox.transaction():
                await self.inbox.mark_processed(command.correlation_id)
                await self.reply_publisher.publish(reply, command.reply_topic)
                
        except Exception as e:
            reply = self.failure_reply(command, str(e))
            await self.reply_publisher.publish(reply, command.reply_topic)
    
    @abstractmethod
    async def execute(self, command: SagaCommand) -> SagaReply:
        """Execute the saga step. Override in subclass."""
        pass
    
    @abstractmethod
    async def compensate(self, command: SagaCommand) -> SagaReply:
        """Compensate the saga step. Override in subclass."""
        pass
    
    # Helper methods for building replies
    def success_reply(self, command: SagaCommand, result: dict) -> SagaReply:
        return SagaReply(
            saga_id=command.saga_id,
            correlation_id=command.correlation_id,
            step_name=command.step_name,
            status=ReplyStatus.SUCCESS,
            result=result,
            error=None,
            participant_id=self.participant_type,
            processed_at=datetime.utcnow(),
            headers=command.headers,
        )
    
    def failure_reply(self, command: SagaCommand, error_message: str) -> SagaReply:
        return SagaReply(
            saga_id=command.saga_id,
            correlation_id=command.correlation_id,
            step_name=command.step_name,
            status=ReplyStatus.FAILURE,
            result={},
            error=ErrorInfo(message=error_message),
            participant_id=self.participant_type,
            processed_at=datetime.utcnow(),
            headers=command.headers,
        )
    
    def compensated_reply(self, command: SagaCommand) -> SagaReply:
        return SagaReply(
            saga_id=command.saga_id,
            correlation_id=command.correlation_id,
            step_name=command.step_name,
            status=ReplyStatus.COMPENSATED,
            result={},
            error=None,
            participant_id=self.participant_type,
            processed_at=datetime.utcnow(),
            headers=command.headers,
        )
```

---

### 5. SagaStateStore

Persistent storage for saga state between message exchanges:

```python
class SagaStateStore(Protocol):
    """
    Storage for distributed saga state.
    
    Required for saga resumption after process restart.
    """
    
    async def create_saga(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        context: dict[str, Any],
        current_step_index: int,
    ) -> None: ...
    
    async def get_saga(self, saga_id: str) -> Optional[SagaState]: ...
    
    async def update_saga(self, state: SagaState) -> None: ...
    
    async def find_timed_out_sagas(self, timeout_threshold: datetime) -> list[SagaState]: ...
    
    async def find_sagas_by_status(self, status: SagaStatus) -> list[SagaState]: ...


@dataclass
class SagaState:
    """Persistent saga state."""
    saga_id: str
    saga_name: str
    status: SagaStatus
    context: dict[str, Any]
    current_step_index: int
    completed_steps: list[str]
    failure_reason: Optional[ErrorInfo]
    created_at: datetime
    updated_at: datetime
```

#### PostgreSQL Implementation

```sql
CREATE TABLE saga_state (
    saga_id         UUID PRIMARY KEY,
    saga_name       VARCHAR(255) NOT NULL,
    status          VARCHAR(50) NOT NULL,
    context         JSONB NOT NULL,
    current_step    INTEGER NOT NULL DEFAULT 0,
    completed_steps JSONB NOT NULL DEFAULT '[]',
    failure_reason  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    timeout_at      TIMESTAMPTZ,
    
    -- Indexes for common queries
    CONSTRAINT saga_state_status_idx 
);

CREATE INDEX saga_state_status_idx ON saga_state(status);
CREATE INDEX saga_state_timeout_idx ON saga_state(timeout_at) WHERE status = 'executing';
```

---

### 6. InboxStorage (Idempotency)

For participants to track processed commands:

```python
class InboxStorage(Protocol):
    """
    Consumer inbox for idempotent command processing.
    
    Prevents duplicate processing when messages are redelivered.
    """
    
    async def exists(self, correlation_id: str) -> bool: ...
    
    async def mark_processed(self, correlation_id: str) -> None: ...
    
    async def cleanup_old_entries(self, older_than: datetime) -> int: ...
```

```sql
CREATE TABLE saga_inbox (
    correlation_id  VARCHAR(255) PRIMARY KEY,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Cleanup job removes entries older than 7 days
CREATE INDEX saga_inbox_processed_at_idx ON saga_inbox(processed_at);
```

---

## Usage Example

### Orchestrator Side (Order Service)

```python
# Define the distributed saga
class OrderSaga(DistributedSaga):
    name = "order_saga"
    version = "1.0"
    
    steps = [
        RemoteStep(
            name="reserve_inventory",
            participant="inventory-service",
            command_topic="inventory.commands",
            timeout=30.0,
            build_command=lambda ctx: {"items": ctx["order_items"]},
        ),
        RemoteStep(
            name="charge_payment",
            participant="payment-service",
            command_topic="payment.commands",
            timeout=60.0,
            build_command=lambda ctx: {
                "amount": ctx["total_amount"],
                "customer_id": ctx["customer_id"],
            },
        ),
        RemoteStep(
            name="create_shipment",
            participant="shipping-service",
            command_topic="shipping.commands",
            timeout=30.0,
            build_command=lambda ctx: {
                "order_id": ctx["order_id"],
                "address": ctx["shipping_address"],
            },
        ),
    ]


# In your API handler
async def create_order(request: CreateOrderRequest):
    saga = OrderSaga(
        state_store=PostgresSagaStateStore(db_pool),
        command_publisher=KafkaCommandPublisher(producer),
    )
    
    saga_id = await saga.start({
        "order_items": request.items,
        "total_amount": request.total,
        "customer_id": request.customer_id,
        "shipping_address": request.address,
    })
    
    return {"order_id": saga_id, "status": "processing"}


# Reply consumer (separate process or async task)
# Each saga type has its own consumer for isolation
async def run_order_saga_reply_consumer():
    consumer = KafkaReplyConsumer(
        topic="saga.replies.order_saga",  # Per-saga-type topic
        group_id="order-saga-orchestrator",
    )
    
    async for message in consumer:
        reply = SagaReply.from_dict(message.value)
        saga = OrderSaga(state_store, command_publisher)
        await saga.on_reply(reply)


# Or use a generic consumer with topic routing
async def run_all_reply_consumers():
    """Start consumers for all registered saga types."""
    saga_registry = {
        "order_saga": OrderSaga,
        "payment_saga": PaymentSaga,
    }
    
    consumers = []
    for saga_name, saga_class in saga_registry.items():
        consumer = create_saga_reply_consumer(
            saga_name=saga_name,
            saga_class=saga_class,
        )
        consumers.append(consumer)
    
    await asyncio.gather(*consumers)
```

### Participant Side (Inventory Service)

```python
class InventoryParticipant(SagaParticipant):
    participant_type = "inventory-service"
    
    def __init__(self, inventory_repo: InventoryRepository, ...):
        super().__init__(inbox_storage, reply_publisher)
        self.inventory_repo = inventory_repo
    
    async def execute(self, command: SagaCommand) -> SagaReply:
        items = command.payload["items"]
        
        # Business logic
        reservation = await self.inventory_repo.reserve_items(
            items=items,
            saga_id=command.saga_id,  # For correlation
        )
        
        return self.success_reply(command, {
            "reservation_id": reservation.id,
            "reserved_items": reservation.items,
        })
    
    async def compensate(self, command: SagaCommand) -> SagaReply:
        reservation_id = command.payload.get("reservation_id")
        
        if reservation_id:
            await self.inventory_repo.release_reservation(reservation_id)
        
        return self.compensated_reply(command)


# Command consumer (main entry point)
async def run_command_consumer():
    consumer = KafkaConsumer("inventory.commands")
    participant = InventoryParticipant(
        inbox_storage=PostgresInboxStorage(db_pool),
        reply_publisher=KafkaReplyPublisher(producer),
        inventory_repo=InventoryRepository(db_pool),
    )
    
    async for message in consumer:
        command = SagaCommand.from_dict(message.value)
        if command.participant == participant.participant_type:
            await participant.process_command(command)
```

---

## Timeout and Recovery

### Timeout Detection

```python
class SagaTimeoutMonitor:
    """
    Background task to detect and handle timed-out sagas.
    
    Runs periodically to find sagas stuck waiting for replies.
    """
    
    def __init__(
        self,
        state_store: SagaStateStore,
        saga_registry: dict[str, type[DistributedSaga]],
    ):
        self.state_store = state_store
        self.saga_registry = saga_registry
    
    async def check_timeouts(self):
        """Find and retry/compensate timed-out sagas."""
        threshold = datetime.utcnow() - timedelta(seconds=60)
        timed_out = await self.state_store.find_timed_out_sagas(threshold)
        
        for saga_state in timed_out:
            saga_class = self.saga_registry[saga_state.saga_name]
            saga = saga_class(self.state_store, ...)
            
            current_step = saga.steps[saga_state.current_step_index]
            
            if saga_state.retry_count < current_step.max_retries:
                # Retry
                await saga._retry_current_step(saga_state)
            else:
                # Start compensation
                await saga._start_compensation(saga_state)
```

### Saga Recovery on Startup

```python
async def recover_sagas_on_startup():
    """
    Resume in-progress sagas after process restart.
    
    Called during application startup.
    """
    executing_sagas = await state_store.find_sagas_by_status(SagaStatus.EXECUTING)
    
    for saga_state in executing_sagas:
        saga_class = saga_registry[saga_state.saga_name]
        saga = saga_class(state_store, command_publisher)
        
        # Re-send the current step command (participant will dedupe)
        await saga._send_current_command(saga_state)
```

---

## Differences from Synchronous Saga

| Aspect | Sync Saga (v1.0) | Distributed Saga (v2.0) |
|--------|------------------|-------------------------|
| **Step Definition** | `@action` decorated method | `RemoteStep` with topics |
| **Execution** | `await saga.execute()` | `await saga.start()` + reply consumer |
| **State Storage** | In-memory during execution | Persistent `SagaStateStore` |
| **Compensation Trigger** | Immediate on failure | Via reply message + timeout |
| **Process Boundary** | Single process | Multiple services |
| **Testing** | Mock functions | Mock broker / integration tests |

---

## Migration Path

### Keeping Both Models

Sagaz v2.0 would support **both** models:

```python
# Sync (existing)
class LocalOrderSaga(Saga):
    @action("create_order")
    async def create_order(self, ctx): ...

# Distributed (new)
class DistributedOrderSaga(DistributedSaga):
    steps = [RemoteStep(...), ...]
```

### Hybrid Saga (Future)

Potential v2.1 feature - mix local and remote steps:

```python
class HybridOrderSaga(Saga):
    @action("validate_order")  # Local
    async def validate(self, ctx): ...
    
    @remote_step(participant="inventory", topic="inventory.commands")
    async def reserve_inventory(self, ctx): ...  # Remote
    
    @action("create_order_record")  # Local
    async def create_record(self, ctx): ...
```

---

## Implementation Phases

| Phase | Scope | Effort |
|-------|-------|--------|
| **Phase 1: Protocol** | `SagaCommand`, `SagaReply`, serialization | 2 days |
| **Phase 2: State Store** | `SagaStateStore`, PostgreSQL impl | 2 days |
| **Phase 3: Orchestrator** | `DistributedSaga`, `RemoteStep` | 3 days |
| **Phase 4: Participant** | `SagaParticipant`, `InboxStorage` | 2 days |
| **Phase 5: Consumers** | Reply consumer, command consumer | 2 days |
| **Phase 6: Timeout/Recovery** | `SagaTimeoutMonitor`, startup recovery | 2 days |
| **Phase 7: Testing** | Unit tests, integration tests | 3 days |
| **Phase 8: Documentation** | API docs, examples, migration guide | 2 days |

**Total estimate**: ~18 days (3-4 weeks)

---

## Decision

**Deferred** - To be implemented when:

1. User demand for distributed sagas materializes
2. Clear use cases with multi-service boundaries
3. Team capacity for the ~3-4 week implementation

For now, Sagaz v1.0's synchronous orchestration handles the primary use case of coordinating multiple operations within a single service boundary.

---

## References

### Foundational Distributed Systems Theory

- Lamport, L. (1978). ["Time, Clocks, and the Ordering of Events in a Distributed System"](https://lamport.azurewebsites.net/pubs/time-clocks.pdf) - *Communications of the ACM*. Defines happened-before relation and logical clocks.
- Lamport, L. (1984). ["Using Time Instead of Timeout for Fault-Tolerant Distributed Systems"](https://lamport.azurewebsites.net/pubs/using-time.pdf) - *ACM Transactions on Programming Languages and Systems*.
- Schneider, F.B. (1990). ["Implementing Fault-Tolerant Services Using the State Machine Approach"](https://www.cs.cornell.edu/fbs/publications/SMSurvey.pdf) - *ACM Computing Surveys*. Tutorial on state machine replication.

### Saga Pattern

- Garcia-Molina, H. & Salem, K. (1987). ["Sagas"](https://www.cs.cornell.edu/andru/cs711/2002fa/reading/sagas.pdf) - *ACM SIGMOD*. Original saga pattern paper.
- [Microservices Patterns: Saga](https://microservices.io/patterns/data/saga.html) - Chris Richardson's modern interpretation.

### Implementations & Frameworks

- [Eventuate Tram Sagas](https://github.com/eventuate-tram/eventuate-tram-sagas) - Java saga framework
- [Axon Framework Saga](https://docs.axoniq.io/reference-guide/axon-framework/sagas) - Event-sourced sagas
- [Temporal.io Workflows](https://temporal.io/) - Alternative durable execution approach

### Related Sagaz Documentation

- [ADR-012: Synchronous Orchestration Model](adr/adr-012-synchronous-orchestration-model.md) - Why v1.0 uses direct calls
- [ADR-011: CDC Support](adr/adr-011-cdc-support.md) - High-throughput outbox upgrade path

