# Configuration Guide

Sagaz provides a unified configuration system through `SagaConfig` that centralizes 
settings for storage, message brokers, and observability.

## Quick Start

```python
from sagaz import SagaConfig, Saga, configure, action

# Create configuration
config = SagaConfig(
    storage=PostgreSQLSagaStorage("postgresql://localhost/db"),
    broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    metrics=True,
    tracing=True,
    logging=True,
)

# Apply globally
configure(config)

# All sagas automatically inherit this config
class OrderSaga(Saga):
    saga_name = "order-processing"
    
    @action("create_order")
    async def create_order(self, ctx):
        return {"order_id": "ORD-123"}
```

---

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `storage` | `SagaStorage` | `InMemorySagaStorage()` | Saga state persistence backend |
| `outbox_storage` | `OutboxStorage` | Auto-derived | Outbox event storage (derived from saga storage if not set) |
| `broker` | `BaseBroker` | `None` | Message broker for outbox pattern |
| `metrics` | `bool \| MetricsSagaListener` | `True` | Enable Prometheus metrics |
| `tracing` | `bool \| TracingSagaListener` | `False` | Enable OpenTelemetry tracing |
| `logging` | `bool \| LoggingSagaListener` | `True` | Enable structured logging |
| `default_timeout` | `float` | `60.0` | Default step timeout in seconds |
| `default_max_retries` | `int` | `3` | Default retry count for failed steps |
| `failure_strategy` | `str` | `"FAIL_FAST_WITH_GRACE"` | Parallel failure strategy |

---

## Storage Backends

### PostgreSQL (Recommended for Production)

```python
from sagaz.storage import PostgreSQLSagaStorage

config = SagaConfig(
    storage=PostgreSQLSagaStorage("postgresql://user:pass@localhost/db")
)
```

### Redis

```python
from sagaz.storage import RedisSagaStorage

config = SagaConfig(
    storage=RedisSagaStorage("redis://localhost:6379/0")
)
```

### In-Memory (Testing Only)

```python
from sagaz.storage import InMemorySagaStorage

config = SagaConfig(
    storage=InMemorySagaStorage()  # This is the default
)
```

---

## Message Brokers

### Kafka

```python
from sagaz.outbox.brokers import KafkaBroker

config = SagaConfig(
    storage=storage,
    broker=KafkaBroker(bootstrap_servers="localhost:9092"),
)
```

### RabbitMQ

```python
from sagaz.outbox.brokers import RabbitMQBroker

config = SagaConfig(
    storage=storage,
    broker=RabbitMQBroker(url="amqp://guest:guest@localhost/"),
)
```

### Redis Streams

```python
from sagaz.outbox.brokers import RedisBroker

config = SagaConfig(
    storage=storage,
    broker=RedisBroker(redis_url="redis://localhost:6379/0"),
)
```

---

## Outbox Storage Derivation

When you set a `broker` but don't explicitly set `outbox_storage`, Sagaz will 
automatically derive the outbox storage from your saga storage:

```python
# Saga storage is PostgreSQL
config = SagaConfig(
    storage=PostgreSQLSagaStorage("postgresql://localhost/db"),
    broker=KafkaBroker(...),
    # outbox_storage auto-derived as PostgreSQLOutboxStorage with same connection!
)
```

### Why This Matters

For the **transactional outbox pattern** to work correctly, both saga state and 
outbox events should be in the **same database transaction**. Deriving the outbox 
storage from the saga storage ensures this.

### Warnings

If you use in-memory or Redis saga storage with a broker, you'll see a warning:

```
WARNING - Broker configured without explicit outbox_storage. 
Using InMemoryOutboxStorage - events will NOT survive restarts. 
For production, set outbox_storage explicitly.
```

---

## Environment Variables

For 12-factor applications, use `SagaConfig.from_env()`:

```python
config = SagaConfig.from_env()
configure(config)
```

### Supported Environment Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `SAGAZ_STORAGE_URL` | `postgresql://localhost/db` | Storage connection string |
| `SAGAZ_BROKER_URL` | `kafka://localhost:9092` | Broker connection string |
| `SAGAZ_METRICS` | `true` / `false` | Enable metrics |
| `SAGAZ_TRACING` | `true` / `false` | Enable tracing |
| `SAGAZ_LOGGING` | `true` / `false` | Enable logging |

### URL Schemes

| Scheme | Storage/Broker |
|--------|----------------|
| `postgresql://`, `postgres://` | PostgreSQLSagaStorage |
| `redis://` | RedisSagaStorage / RedisBroker |
| `kafka://` | KafkaBroker |
| `amqp://`, `rabbitmq://` | RabbitMQBroker |
| `memory://` | InMemorySagaStorage / InMemoryBroker |

---

## Immutable Updates

`SagaConfig` supports immutable updates for runtime changes:

```python
# Create a new config with different storage
new_config = config.with_storage(new_storage)

# Create a new config with different broker
new_config = config.with_broker(new_broker, outbox_storage=new_outbox)
```

---

## Per-Saga Configuration

You can override global config for specific sagas:

```python
# Global config
configure(SagaConfig(metrics=True, logging=True))

# This saga uses a different config
special_config = SagaConfig(metrics=False, logging=True)

saga = SpecialSaga(config=special_config)
```

---

## Custom Listeners

You can pass custom listener instances instead of booleans:

```python
from sagaz.listeners import LoggingSagaListener, MetricsSagaListener

config = SagaConfig(
    logging=LoggingSagaListener(level=logging.DEBUG),
    metrics=MetricsSagaListener(prefix="my_app_"),
    tracing=False,
)
```

---

## Configuration Hierarchy

Configuration is resolved in this order (first wins):

1. **Explicit `config=` parameter** passed to Saga constructor
2. **Class-level `listeners`** attribute on Saga subclass
3. **Global configuration** set via `configure(config)`
4. **Default SagaConfig** (in-memory, metrics + logging enabled)

```python
# Priority 1: Explicit config
saga = MySaga(config=explicit_config)

# Priority 2: Class listeners
class MySaga(Saga):
    listeners = [MyCustomListener()]  # These override global config

# Priority 3: Global config
configure(global_config)

# Priority 4: Defaults (automatic)
```
