# Quickstart Guide

Get Sagaz running in 5 minutes.

## Installation

```bash
pip install sagaz
```

Or with extras:

```bash
pip install sagaz[postgres,rabbitmq]  # For production
pip install sagaz[postgres,kafka]     # With Kafka
```

## Basic Usage (Declarative API)

### 1. Define a Saga

```python
from sagaz import Saga, action, compensate

class OrderSaga(Saga):
    saga_name = "order-processing"
    
    @action("reserve_inventory")
    async def reserve_inventory(self, ctx):
        # Reserve items...
        return {"reservation_id": "RES-123"}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        # Release reservation...
        pass
    
    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx):
        # Charge customer...
        return {"payment_id": "PAY-456"}
    
    @compensate("charge_payment")
    async def refund_payment(self, ctx):
        # Refund payment...
        pass
```

### 2. Execute the Saga

```python
saga = OrderSaga()
result = await saga.run({
    "order_id": "ORD-123",
    "amount": 99.99
})

if "payment_id" in result:
    print(f"Order processed: {result['payment_id']}")
```

---

## Step Lifecycle Hooks

Add per-step callbacks for fine-grained control:

```python
from sagaz import Saga, action, compensate

async def log_step_start(ctx, step_name):
    print(f"Starting step: {step_name}")

async def publish_order_created(ctx, step_name, result):
    await event_bus.publish("order.created", result)

async def alert_on_failure(ctx, step_name, error):
    await pagerduty.alert(f"Step {step_name} failed: {error}")

class OrderSaga(Saga):
    @action(
        "create_order",
        on_enter=log_step_start,
        on_success=publish_order_created,
        on_failure=alert_on_failure,
    )
    async def create_order(self, ctx):
        return {"order_id": "ORD-123"}
```

### Available Hooks

| Hook | Signature | When Called |
|------|-----------|-------------|
| `on_enter` | `(ctx, step_name)` | Before step executes |
| `on_success` | `(ctx, step_name, result)` | After successful completion |
| `on_failure` | `(ctx, step_name, error)` | When step raises exception |
| `on_compensate` | `(ctx, step_name)` | When compensation runs |

---

## Saga Listeners (Cross-Cutting Concerns)

For metrics, logging, tracing, or outbox publishing across ALL steps:

```python
from sagaz import Saga, action
from sagaz.listeners import (
    LoggingSagaListener,
    MetricsSagaListener,
    OutboxSagaListener,
)

class OrderSaga(Saga):
    saga_name = "order-processing"
    listeners = [
        LoggingSagaListener(),
        MetricsSagaListener(),
        OutboxSagaListener(storage=outbox_storage),
    ]
    
    @action("create_order")
    async def create_order(self, ctx):
        return {"order_id": "ORD-123"}
    
    @action("charge_payment", depends_on=["create_order"])
    async def charge_payment(self, ctx):
        return {"charge_id": "CHG-456"}
```

### Built-in Listeners

| Listener | Purpose |
|----------|---------|
| `LoggingSagaListener` | Structured logging for all events |
| `MetricsSagaListener` | Prometheus-compatible metrics |
| `TracingSagaListener` | OpenTelemetry distributed tracing |
| `OutboxSagaListener` | Publish events to outbox for reliable delivery |

### Custom Listeners

```python
from sagaz.listeners import SagaListener

class SlackNotificationListener(SagaListener):
    async def on_saga_failed(self, saga_name, saga_id, ctx, error):
        await slack.post(f"🔥 Saga {saga_name} failed: {error}")
    
    async def on_saga_complete(self, saga_name, saga_id, ctx):
        await slack.post(f"✅ Saga {saga_name} completed")

class OrderSaga(Saga):
    listeners = [SlackNotificationListener()]
```

---

## Global Configuration with SagaConfig 🆕

Configure storage, broker, and observability in one place:

```python
from sagaz import SagaConfig, Saga, configure, action
from sagaz.storage import PostgreSQLSagaStorage
from sagaz.outbox.brokers import KafkaBroker

# 1. Create unified configuration
config = SagaConfig(
    storage=PostgreSQLSagaStorage("postgresql://localhost/db"),
    broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    metrics=True,      # Enable Prometheus metrics
    tracing=True,      # Enable OpenTelemetry tracing
    logging=True,      # Enable structured logging
)

# 2. Apply globally - all sagas inherit this config
configure(config)

# 3. Sagas automatically get storage and listeners!
class OrderSaga(Saga):
    saga_name = "order-processing"
    
    @action("create_order")
    async def create_order(self, ctx):
        return {"order_id": "ORD-123"}
```

### From Environment Variables (12-Factor App)

```python
# Set environment variables:
# SAGAZ_STORAGE_URL=postgresql://localhost/db
# SAGAZ_BROKER_URL=kafka://localhost:9092
# SAGAZ_METRICS=true
# SAGAZ_TRACING=true

config = SagaConfig.from_env()
configure(config)
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `storage` | `SagaStorage` | `InMemorySagaStorage()` | Saga state persistence |
| `broker` | `BaseBroker` | `None` | Message broker for outbox |
| `outbox_storage` | `OutboxStorage` | Auto-derived | Outbox event storage |
| `metrics` | `bool` | `True` | Enable metrics collection |
| `tracing` | `bool` | `False` | Enable distributed tracing |
| `logging` | `bool` | `True` | Enable structured logging |
| `default_timeout` | `float` | `60.0` | Default step timeout (seconds) |
| `default_max_retries` | `int` | `3` | Default retry count |

---

## With Transactional Outbox

For reliable event delivery:

### 1. Setup Database

```sql
-- Run migration
CREATE TABLE saga_outbox (
    event_id UUID PRIMARY KEY,
    saga_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2. Configure Storage & Broker

```python
from sagaz.outbox import OutboxWorker
from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
from sagaz.outbox.brokers.rabbitmq import RabbitMQBroker

# Storage
storage = PostgreSQLOutboxStorage(
    connection_string="postgresql://user:pass@localhost/db"
)

# Broker
broker = RabbitMQBroker(
    url="amqp://guest:guest@localhost/"
)
```

### 3. Run Worker

```python
from sagaz.outbox import OutboxWorker, OutboxConfig

config = OutboxConfig(
    batch_size=100,
    poll_interval_seconds=1.0,
    max_retries=5,
)

worker = OutboxWorker(storage, broker, config)
await worker.start()  # Runs until stopped
```

---

## Deploy to Kubernetes

```bash
# Create namespace and secrets
kubectl create namespace sagaz
kubectl apply -f k8s/secrets-local.yaml

# Deploy PostgreSQL
kubectl apply -f k8s/postgresql-local.yaml

# Run migrations
kubectl apply -f k8s/migration-job.yaml

# Deploy RabbitMQ
kubectl apply -f k8s/rabbitmq.yaml

# Deploy workers
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/outbox-worker.yaml

# Verify
kubectl get pods -n sagaz
```

---

## Visualize Your Saga

Generate Mermaid diagrams to visualize your saga structure:

```python
saga = OrderSaga()

# Generate basic diagram
print(saga.to_mermaid())

# Or with markdown code fence
print(saga.to_mermaid_markdown())
```

**Output:**
```mermaid
flowchart TB
    START((●))
    reserve_inventory([reserve_inventory])
    charge_payment[charge_payment]
    SUCCESS((◎))
    START --> reserve_inventory
    reserve_inventory --> charge_payment
    charge_payment --> SUCCESS
```

To visualize a specific execution from storage:

```python
diagram = await saga.to_mermaid_with_execution(
    saga_id="abc-123",
    storage=PostgreSQLSagaStorage(...)
)
```

---

## Next Steps

| Topic | Link |
|-------|------|
| Configuration Guide | [Configuration](guides/configuration.md) |
| Mermaid Visualization | [Diagram Guide](guides/mermaid.md) |
| Grafana Dashboards | [Grafana Setup](../grafana/README.md) |
| Architecture | [Overview](architecture/overview.md) |
| Full API Reference | [API Docs](reference/api.md) |
| Kubernetes Deployment | [K8s Guide](guides/kubernetes.md) |
| Performance Tuning | [Benchmarking](guides/benchmarking.md) |
