# ADR-025: Event-Driven Triggers & Auto-Discovery

## Status

**Accepted** | Date: 2026-01-09 | Priority: High | Target: v1.3.0

## Dependencies

**Prerequisites**: None (independent feature)

**Enables**:
- Streaming MLOps workflows
- Event-driven microservices architectures
- Automated saga triggering from Kafka, RabbitMQ, Redis, webhooks, cron

**Synergies**:
- ADR-021: Context Streaming (triggers can spawn streaming sagas)
- ADR-013: Fluss Analytics (triggers consume analytics events)
- ADR-011: CDC (CDC events can trigger sagas)

**Roadmap**: ⭐ **Phase 2 (v1.3.0)** - High priority, enables streaming use cases

## Context

Current Sagaz implementations are primarily imperative: a user explicitly instantiates a Saga and calls `run()`. While this works for request-response flows (e.g., REST APIs), it creates friction for **event-driven architectures** and **streaming MLOps** where sagas should reactive to external events (Kafka messages, file uploads, schedule ticks).

### Requirements

1.  **Reactive Sagas**: Sagas should start automatically based on external events.
2.  **Auto-Discovery**: Developers shouldn't need to manually register every saga class with an orchestrator. Simply defining or importing the class should be enough.
3.  **Flexible Triggers**: A single saga might be triggered by multiple sources (e.g., Kafka topic, Cron schedule, Webhook).
4.  **Unified API**: Avoid creating new types like `@streaming_action` if the standard `@action` can support generators.

## Decision

### 1. The `@trigger` Decorator

We will introduce a `@trigger` decorator that can be applied to methods within a `Saga` class. These methods act as **transformers**, converting an external event into the initial `SagaContext`.

```python
class ModelRetrainingSaga(Saga):
    saga_name = "model-retraining"

    @trigger(source="kafka", topic="model.drift")
    def on_drift_detected(self, event: DriftEvent):
        # Transform event -> context
        if event.score > 0.5:
            return {"model_id": event.model_id, "reason": "drift"}
        return None # Skip execution

    @trigger(source="cron", schedule="@daily")
    def on_daily_schedule(self, tick):
        return {"model_id": "all", "reason": "scheduled"}

    @action("train_model")
    async def train(self, ctx):
        ...
```

### 2. Auto-Discovery Mechanism

We will use a **Global Registry** pattern combined with Python's import system.

*   The `Saga` base class will use `__init_subclass__` to automatically register any subclass that contains `@trigger` decorated methods into a global `sagaz.triggers.registry`.
*   Users only need to ensure the module containing the Saga is imported.

```python
# In sagaz/registry.py
_registry = {}

# In sagaz/core.py (Saga class)
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    # Scan for methods with _trigger_metadata
    for name, method in cls.__dict__.items():
        if hasattr(method, "_trigger_metadata"):
           register_trigger(cls, method)
```

### 4. Event Sources

Triggers support **all message brokers** that Sagaz currently supports, plus additional sources:

| Source | Description | Sagaz Support |
|--------|-------------|---------------|
| `kafka` | Apache Kafka topic consumer | ✅ Existing |
| `rabbitmq` | RabbitMQ queue/exchange | ✅ Existing |
| `redis` | Redis Streams | ✅ Existing |
| `pulsar` | Apache Pulsar | 🔜 Planned |
| `cron` | Scheduled execution | 🆕 New |
| `webhook` | HTTP endpoint | 🆕 New |
| `file` | File system watch | 🆕 New |
| `sqs` | AWS SQS | 🆕 New |
| `custom` | User-defined source | 🆕 New |

#### Message Broker Examples

**Kafka:**
```python
@trigger(source="kafka", topic="model.drift", group_id="retraining-service")
def on_drift_kafka(self, event):
    return {"model_id": event["model_id"], "source": "kafka"}
```

**RabbitMQ:**
```python
@trigger(
    source="rabbitmq",
    queue="ml.retraining",
    exchange="model-events",
    routing_key="drift.*"
)
def on_drift_rabbit(self, event):
    return {"model_id": event["model_id"], "source": "rabbitmq"}
```

**Redis Streams:**
```python
@trigger(
    source="redis",
    stream="model:events",
    consumer_group="retraining-workers"
)
def on_drift_redis(self, event):
    return {"model_id": event["model_id"], "source": "redis"}
```

#### Other Source Examples

**Cron (Scheduled):**
```python
@trigger(source="cron", schedule="0 */6 * * *")  # Every 6 hours
def on_schedule(self, tick):
    return {"batch_mode": True, "triggered_at": tick.timestamp}

# Or use shortcuts
@trigger(source="cron", schedule="@daily")
def on_daily(self, tick):
    return {"task": "daily_cleanup"}
```

**Webhook (HTTP):**
```python
@trigger(
    source="webhook",
    path="/webhooks/deploy/{model_id}",
    method="POST",
    auth="bearer"  # Validates Authorization header
)
def on_deploy_webhook(self, request):
    return {
        "model_id": request.path_params["model_id"],
        "payload": request.json()
    }
```

**File Watch:**
```python
@trigger(
    source="file",
    path="/data/uploads/",
    pattern="*.csv",
    event_type="created"  # or "modified", "deleted"
)
def on_file_upload(self, file_event):
    return {"file_path": file_event.path, "size": file_event.size}
```

**AWS SQS:**
```python
@trigger(
    source="sqs",
    queue_url="https://sqs.us-east-1.amazonaws.com/123456/events",
    visibility_timeout=300
)
def on_sqs_message(self, event):
    return {"message_id": event["MessageId"]}
```

### 5. Error Handling & Resilience

**Trigger Method Failures:**
```python
@trigger(source="rabbitmq", queue="events")  # or kafka, redis, etc.
def on_event(self, event):
    if not event.is_valid():
        raise InvalidEventError()  # Event goes to DLQ, saga doesn't start
    return {"data": event.payload}
```

**Saga Execution Failures:**
- If trigger method returns a context, saga starts
- If saga fails during execution, normal compensation runs
- Failed events can be retried based on `retry_policy`

**Dead Letter Queue:**
```python
config = TriggerConfig(
    dead_letter_topic="failed-triggers",
    max_retries=3,
    retry_backoff_seconds=[10, 60, 300]
)
```

### 6. Idempotency

Triggers integrate with the existing inbox pattern:

```python
@trigger(source="kafka", topic="orders", idempotency_key=lambda e: e.message_id)
# Also works with RabbitMQ, Redis, SQS, etc.
def on_order(self, event):
    # Automatically deduplicated via inbox
    return {"order_id": event.order_id}
```

### 7. Integration with Existing Components

**Listeners:**
```python
# Trigger events are observable
class TriggerListener(SagaListener):
    async def on_trigger_received(self, saga_name, event_source, event):
        logger.info(f"Saga {saga_name} triggered by {event_source}")
    
    async def on_trigger_filtered(self, saga_name, event, reason):
        logger.debug(f"Event filtered: {reason}")
```

**Outbox Pattern:**
Triggered sagas can still use `OutboxSagaListener` to emit events:
```python
class RetrainingSaga(Saga):
    listeners = [OutboxSagaListener(storage)]
    
    @trigger(source="kafka", topic="model.drift")  # Any broker works
    def on_drift(self, event): ...
    
    @action("train")
    async def train(self, ctx):
        # This will emit to outbox as normal
        return {"model_version": "v2"}
```

**Storage:**
Trigger events are optionally persisted for audit:
```python
config = TriggerConfig(
    persist_events=True,  # Store original event in saga_executions
    event_retention_days=30
)
```

### 3. Unified `@action` for Streaming

Instead of a separate `@streaming_action`, the standard `@action` decorator will detect if the decorated function is an **async generator**.

*   If it returns a value: Standard execution.
*   If it `yield`s: Streaming execution (compatible with ADR-021).

```python
@action("process_stream")
async def process(self, ctx):
    async for record in ctx.stream("input"):
        yield transform(record)
```

## Consequences

### ✅ Pros
*   **Zero Boilerplate**: No explicit `orchestrator.register(MySaga)` calls needed.
*   **Decoupled**: Saga definition includes its own trigger logic; infrastructure just runs it.
*   **Polymorphic**: One saga can respond to many different event types.
*   **Simplicity**: No new `@streaming_action` decorator to learn.

### ❌ Cons
*   **Import Side-Effects**: Auto-discovery relies on side-effects of importing modules, which can sometimes be confusing (if a file isn't imported, the trigger doesn't exist).
*   **Registry Global State**: Managing global state requires care, especially in testing (needs `registry.clear()`).

### ⚠️ Risks
*   **Resource Exhaustion**: High event throughput could spawn too many concurrent sagas.
*   **Testing Complexity**: Need clear patterns for testing triggered sagas.

## Concurrency Control & Backpressure

### Rate Limiting

```python
@trigger(
    source="rabbitmq",  # Works with any broker: kafka, redis, rabbitmq, sqs
    queue="events",
    max_concurrent_sagas=100,  # Max 100 sagas executing simultaneously
    rate_limit_per_second=10   # Start at most 10 sagas/second
)
def on_event(self, event): ...
```

### Semantic Concurrency Control

```python
@trigger(
    source="redis",  # Semantic concurrency works with all brokers
    stream="orders",
    concurrency_key=lambda event: event.user_id  # One saga per user at a time
)
def on_order(self, event):
    return {"order_id": event.order_id, "user_id": event.user_id}
```

### Backpressure Strategies

```python
config = TriggerConfig(
    backpressure_strategy="drop_oldest",  # or "block", "drop_newest", "reject"
    queue_size=1000,  # Buffer size before applying backpressure
)
```

| Strategy | Behavior |
|----------|----------|
| `block` | Stop consuming events until sagas complete (Kafka lag increases) |
| `drop_oldest` | Drop oldest buffered events when queue is full |
| `drop_newest` | Reject new events when queue is full |
| `reject` | Send new events to DLQ when queue is full |

## Testing Triggered Sagas

```python
# test_sagas.py
from sagaz.testing import TriggerTestHarness

async def test_drift_trigger():
    saga = ModelRetrainingSaga()
    harness = TriggerTestHarness(saga)
    
    # Simulate event
    event = DriftEvent(model_id="model-123", score=0.8)
    context = await harness.trigger("on_drift_detected", event)
    
    assert context["model_id"] == "model-123"
    assert context["reason"] == "drift"

async def test_trigger_filtering():
    saga = ModelRetrainingSaga()
    harness = TriggerTestHarness(saga)
    
    # Low score - should be filtered
    event = DriftEvent(model_id="model-123", score=0.3)
    context = await harness.trigger("on_drift_detected", event)
    
    assert context is None  # Filtered out
```

## Implementation Plan

1.  **Registry Module**: Create `sagaz.registry` to hold trigger mappings.
2.  **Update Saga Metaclass**: Hook into `__init_subclass__` to populate registry.
3.  **Decorators**: Implement `@trigger` to tag methods with metadata.
4.  **Orchestrator Update**: Add `orchestrator.listen()` that consumes from the registry.

## Example Usage

### Multi-Broker Saga

```python
# sagas.py
from sagaz import Saga, action, trigger

class OrderSaga(Saga):
    saga_name = "order-processing"
    
    # Triggered from Kafka
    @trigger(source="kafka", topic="orders.created", group_id="order-service")
    def from_kafka(self, msg):
        return {"order_id": msg["id"], "source": "kafka"}
    
    # Triggered from RabbitMQ
    @trigger(source="rabbitmq", queue="orders", exchange="ecommerce")
    def from_rabbitmq(self, msg):
        return {"order_id": msg["order_id"], "source": "rabbitmq"}
    
    # Triggered from HTTP webhook
    @trigger(source="webhook", path="/api/orders", method="POST")
    def from_webhook(self, request):
        return {"order_id": request.json()["id"], "source": "webhook"}
    
    # Triggered on schedule (batch processing)
    @trigger(source="cron", schedule="@hourly")
    def from_schedule(self, tick):
        return {"batch_mode": True, "source": "cron"}

    @action("process")
    async def process(self, ctx):
        # Business logic here
        order_id = ctx.get("order_id")
        source = ctx.get("source")
        logger.info(f"Processing order {order_id} from {source}")
        ...

# main.py
import sagaz
# Just import the modules - triggers auto-discover!
import my_app.sagas 

# Start all trigger listeners
await sagaz.start_triggers()  # Starts Kafka, RabbitMQ, webhook server, cron scheduler
```
