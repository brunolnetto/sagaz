# Multi-Sink Fan-out Pattern

## Overview

The Multi-Sink Fan-out pattern allows saga events to be routed to multiple destinations simultaneously. This is already **natively supported** in Sagaz via multiple `SagaListener` registrations.

## Architecture

```
                          ┌─────────────────┐
                          │  Fluss/Iceberg  │  Real-time + Historical Analytics
                          │  (OLAP Sink)    │
                          └────────▲────────┘
                                   │
┌─────────────┐     ┌──────────────┼──────────────┐
│   Saga      │────▶│      SagaListeners          │
│  Executor   │     │  ┌─────────────────────┐    │
└─────────────┘     │  │ FlussAnalyticsListener   │────▶ Fluss
                    │  ├─────────────────────┤    │
                    │  │ ElasticsearchListener    │────▶ Elasticsearch (Search)
                    │  ├─────────────────────┤    │
                    │  │ RedisCacheListener       │────▶ Redis (Cache)
                    │  ├─────────────────────┤    │
                    │  │ OutboxSagaListener       │────▶ Kafka/RabbitMQ
                    │  ├─────────────────────┤    │
                    │  │ MetricsSagaListener      │────▶ Prometheus
                    │  └─────────────────────┘    │
                    └─────────────────────────────┘
```

## Implementation

### Registering Multiple Listeners

```python
from sagaz import Saga
from sagaz.listeners import (
    OutboxSagaListener,
    MetricsSagaListener,
    TracingSagaListener,
)
from myapp.listeners import (
    FlussAnalyticsListener,
    ElasticsearchListener,
    RedisCacheListener,
)

# Create listeners
listeners = [
    # Core observability
    MetricsSagaListener(registry=prometheus_registry),
    TracingSagaListener(tracer=opentelemetry_tracer),
    
    # Event publishing (outbox)
    OutboxSagaListener(storage=postgres_storage),
    
    # Analytics sink
    FlussAnalyticsListener(fluss_client=fluss),
    
    # Search sink
    ElasticsearchListener(es_client=elasticsearch),
    
    # Cache sink
    RedisCacheListener(redis_client=redis),
]

# Register all listeners with saga
saga = OrderSaga(listeners=listeners)

# Or add dynamically
saga.add_listener(AuditLogListener(audit_storage))
```

### Custom Sink Listener Template

```python
from sagaz.listeners import SagaListener
from typing import Any

class CustomSinkListener(SagaListener):
    """Template for a custom sink listener."""
    
    def __init__(self, sink_client: Any):
        self.sink = sink_client
    
    async def on_saga_started(
        self, saga_id: str, saga_name: str, context: dict
    ):
        await self.sink.write({
            "event_type": "saga_started",
            "saga_id": saga_id,
            "saga_name": saga_name,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_step_completed(
        self, saga_id: str, step_name: str, result: Any, duration_ms: int
    ):
        await self.sink.write({
            "event_type": "step_completed",
            "saga_id": saga_id,
            "step_name": step_name,
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_step_failed(
        self, saga_id: str, step_name: str, error: Exception, duration_ms: int
    ):
        await self.sink.write({
            "event_type": "step_failed",
            "saga_id": saga_id,
            "step_name": step_name,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_saga_completed(self, saga_id: str, total_duration_ms: int):
        await self.sink.write({
            "event_type": "saga_completed",
            "saga_id": saga_id,
            "total_duration_ms": total_duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    async def on_saga_rolled_back(self, saga_id: str, total_duration_ms: int):
        await self.sink.write({
            "event_type": "saga_rolled_back",
            "saga_id": saga_id,
            "total_duration_ms": total_duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })
```

## Common Sink Implementations

### Elasticsearch (Search)

```python
from elasticsearch import AsyncElasticsearch

class ElasticsearchListener(SagaListener):
    """Index saga events in Elasticsearch for search."""
    
    def __init__(self, es_client: AsyncElasticsearch, index: str = "saga-events"):
        self.es = es_client
        self.index = index
    
    async def on_step_completed(self, saga_id: str, step_name: str, result: Any, duration_ms: int):
        await self.es.index(
            index=self.index,
            document={
                "saga_id": saga_id,
                "step_name": step_name,
                "status": "completed",
                "duration_ms": duration_ms,
                "@timestamp": datetime.utcnow().isoformat(),
            }
        )
```

### Redis (Cache)

```python
import redis.asyncio as redis

class RedisCacheListener(SagaListener):
    """Cache saga state in Redis for fast lookups."""
    
    def __init__(self, redis_client: redis.Redis, ttl: int = 3600):
        self.redis = redis_client
        self.ttl = ttl
    
    async def on_saga_started(self, saga_id: str, saga_name: str, context: dict):
        await self.redis.hset(
            f"saga:{saga_id}",
            mapping={
                "name": saga_name,
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
            }
        )
        await self.redis.expire(f"saga:{saga_id}", self.ttl)
    
    async def on_saga_completed(self, saga_id: str, total_duration_ms: int):
        await self.redis.hset(f"saga:{saga_id}", "status", "completed")
        await self.redis.hset(f"saga:{saga_id}", "duration_ms", total_duration_ms)
```

### Webhook (External Notification)

```python
import httpx

class WebhookListener(SagaListener):
    """Notify external systems via webhook."""
    
    def __init__(self, webhook_url: str, secret: str | None = None):
        self.url = webhook_url
        self.secret = secret
    
    async def on_saga_completed(self, saga_id: str, total_duration_ms: int):
        async with httpx.AsyncClient() as client:
            await client.post(
                self.url,
                json={
                    "event": "saga_completed",
                    "saga_id": saga_id,
                    "duration_ms": total_duration_ms,
                },
                headers={"X-Webhook-Secret": self.secret} if self.secret else {},
            )
```

## Best Practices

### 1. Listener Independence

Each listener should be independent and not depend on others:

```python
# ✅ Good - each listener handles its own errors
class ResilientListener(SagaListener):
    async def on_saga_started(self, saga_id: str, saga_name: str, context: dict):
        try:
            await self._write_to_sink(...)
        except Exception as e:
            logger.error(f"Listener failed: {e}")
            # Don't re-raise - don't block other listeners
```

### 2. Async All the Way

All listener methods should be async for parallel execution:

```python
# ✅ Good - async enables parallel fan-out
async def on_step_completed(self, ...):
    await self.sink.write_async(...)

# ❌ Bad - blocks other listeners
def on_step_completed(self, ...):
    self.sink.write_sync(...)  # Blocks!
```

### 3. Configure Timeouts

Prevent slow sinks from blocking saga execution:

```python
class TimeoutWrappedListener(SagaListener):
    def __init__(self, inner: SagaListener, timeout_ms: int = 1000):
        self.inner = inner
        self.timeout = timeout_ms / 1000
    
    async def on_step_completed(self, *args, **kwargs):
        try:
            await asyncio.wait_for(
                self.inner.on_step_completed(*args, **kwargs),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Listener timed out, continuing...")
```

### 4. Monitor Listener Health

Track listener performance:

```python
class MonitoredListener(SagaListener):
    def __init__(self, inner: SagaListener, name: str):
        self.inner = inner
        self.name = name
    
    async def on_step_completed(self, *args, **kwargs):
        start = time.monotonic()
        try:
            await self.inner.on_step_completed(*args, **kwargs)
            listener_success.labels(listener=self.name).inc()
        except Exception:
            listener_errors.labels(listener=self.name).inc()
            raise
        finally:
            duration = time.monotonic() - start
            listener_duration.labels(listener=self.name).observe(duration)
```

## Alternative: Kafka Consumer Groups

For more decoupled fan-out, use multiple Kafka consumer groups:

```
┌─────────────┐     ┌─────────────┐
│   Saga      │────▶│   Outbox    │────▶ Kafka Topic: saga-events
│  Executor   │     │  Listener   │
└─────────────┘     └─────────────┘              │
                                                 ├──────▶ Consumer Group: analytics
                                                 │              └──▶ Fluss
                                                 │
                                                 ├──────▶ Consumer Group: search
                                                 │              └──▶ Elasticsearch
                                                 │
                                                 └──────▶ Consumer Group: alerts
                                                                └──▶ PagerDuty
```

This approach:
- Decouples sinks from saga execution
- Enables independent scaling
- Provides replay capability
- Adds latency vs in-process listeners

## Related Documentation

- [SagaListener API](../api/listeners.md)
- [Fluss Analytics](../architecture/fluss-analytics.md)
- [Dead Letter Queue](dead-letter-queue.md)
