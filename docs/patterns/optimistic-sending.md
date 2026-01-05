# Optimistic Sending Pattern

## Overview

Optimistic sending is a performance optimization that attempts to publish events immediately after a transaction commits, rather than waiting for the polling worker. This reduces latency from ~100ms to <10ms in the happy path.

## How It Works

```
Traditional Flow (100ms):
1. Transaction commits (saga state + outbox event)
2. Wait for polling worker (~100ms)
3. Worker claims event
4. Worker publishes to broker
5. Event delivered

Optimistic Flow (<10ms):
1. Transaction commits (saga state + outbox event)
2. ⚡ Immediately attempt publish to broker
3. If SUCCESS: Mark as sent, done! (<10ms)
4. If FAILURE: Leave for polling worker (safety net)
```

## Key Benefits

- **10x faster** - <10ms vs ~100ms latency
- **Zero risk** - Failures gracefully fallback to polling worker
- **Feature flag** - Can enable/disable easily
- **Full metrics** - Track success/failure rates

## Usage

### Basic Setup

```python
from sagaz.outbox import OptimisticPublisher
from sagaz.outbox.storage import PostgreSQLOutboxStorage
from sagaz.outbox.brokers import KafkaBroker

# Initialize components
storage = PostgreSQLOutboxStorage("postgresql://localhost/db")
broker = KafkaBroker(bootstrap_servers="localhost:9092")

await storage.initialize()
await broker.connect()

# Create optimistic publisher
publisher = OptimisticPublisher(
    storage=storage,
    broker=broker,
    enabled=True,          # Feature flag
    timeout_seconds=0.5    # Aggressive timeout
)
```

### Publishing Events

```python
# In your application code
async with db.transaction():
    # 1. Update saga state
    await saga_storage.save(saga)
    
    # 2. Insert outbox event (atomically)
    event = OutboxEvent(
        saga_id=saga.saga_id,
        event_type="OrderCreated",
        aggregate_type="order",
        aggregate_id=order_id,
        payload={"order_id": order_id, "amount": 99.99},
        headers={"trace_id": trace_id}
    )
    await outbox_storage.insert(event)
    
    # 3. Commit transaction
    # (await db.commit() if not using context manager)

# 4. AFTER commit succeeds, attempt optimistic publish
success = await publisher.publish_after_commit(event)

if success:
    logger.info("Published immediately! (<10ms)")
else:
    logger.info("Will be picked up by polling worker (~100ms)")
```

## Configuration

```python
publisher = OptimisticPublisher(
    storage=storage,
    broker=broker,
    
    # Feature flag - disable in production if needed
    enabled=True,
    
    # Timeout for broker publish attempt
    # Keep this low to avoid blocking application
    timeout_seconds=0.5,  # 500ms max
)
```

## Monitoring

### Prometheus Metrics

```python
# Total attempts
outbox_optimistic_send_attempts_total

# Successful immediate publishes
outbox_optimistic_send_success_total

# Failures (will fallback to polling)
outbox_optimistic_send_failures_total{reason="timeout|BrokerError"}

# Latency distribution
outbox_optimistic_send_latency_seconds
```

### Grafana Queries

```promql
# Success rate
rate(outbox_optimistic_send_success_total[5m]) / 
rate(outbox_optimistic_send_attempts_total[5m])

# P99 latency
histogram_quantile(0.99, 
  rate(outbox_optimistic_send_latency_seconds_bucket[5m])
)

# Failure rate by reason
sum by (reason) (
  rate(outbox_optimistic_send_failures_total[5m])
)
```

## Best Practices

### 1. Always Call AFTER Commit

```python
# ❌ WRONG - Before commit
await publisher.publish_after_commit(event)
await db.commit()  # If this fails, event already published!

# ✅ CORRECT - After commit
await db.commit()
await publisher.publish_after_commit(event)
```

### 2. Don't Block on Failures

```python
# ✅ CORRECT - Non-blocking, fire and forget
success = await publisher.publish_after_commit(event)
# Continue immediately, don't retry here

# ❌ WRONG - Blocking retry loop
while not await publisher.publish_after_commit(event):
    await asyncio.sleep(1)  # Blocks application!
```

### 3. Use Aggressive Timeouts

```python
# ✅ CORRECT - Fast timeout, fallback quickly
publisher = OptimisticPublisher(
    storage, broker,
    timeout_seconds=0.5  # 500ms max
)

# ❌ WRONG - Long timeout blocks application
publisher = OptimisticPublisher(
    storage, broker,
    timeout_seconds=5.0  # Too long!
)
```

### 4. Feature Flag for Safety

```python
# Enable/disable based on environment
import os

publisher = OptimisticPublisher(
    storage, broker,
    enabled=os.getenv("OPTIMISTIC_SEND_ENABLED", "true").lower() == "true"
)
```

## Failure Handling

### Automatic Fallback

If optimistic publish fails for ANY reason:
- Event remains in "pending" status
- Polling worker will pick it up
- No manual intervention needed
- No data loss possible

### Common Failure Scenarios

```python
# 1. Broker timeout
# → Event picked up by worker in ~100ms

# 2. Broker connection error
# → Event picked up by worker in ~100ms

# 3. Network partition
# → Event picked up by worker when network recovers

# 4. Application crash after commit but before optimistic send
# → Event picked up by worker on next poll
```

## Performance Tuning

### Baseline Performance

| Metric | Value |
|--------|-------|
| Traditional (polling) | ~100ms |
| Optimistic (success) | <10ms |
| Optimistic (failure) | ~100ms (fallback) |

### Expected Success Rate

With healthy infrastructure:
- **95-99%** success rate expected
- **1-5%** timeouts/failures (normal)
- All failures handled by polling worker

### When to Disable

Consider disabling if:
- Broker is unstable (>10% failure rate)
- Application latency is not critical
- Troubleshooting message delivery issues

## Troubleshooting

### High Failure Rate

```bash
# Check metrics
curl http://localhost:8000/metrics | grep optimistic_send_failures

# Check if broker is healthy
kubectl get pods -l app=kafka
kubectl logs -f kafka-0

# Temporarily disable
export OPTIMISTIC_SEND_ENABLED=false
```

### Messages Not Being Published

```bash
# 1. Check if optimistic send succeeded
# Look for outbox_optimistic_send_success_total

# 2. If not, check if worker is running
kubectl get pods -l app=outbox-worker

# 3. Check worker logs
kubectl logs -f deployment/outbox-worker

# 4. Check pending count
SELECT COUNT(*) FROM saga_outbox WHERE status='pending';
```

## Kubernetes Configuration

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: outbox-worker-config
data:
  # Enable optimistic sending
  ENABLE_OPTIMISTIC_SEND: "true"
  
  # Timeout for optimistic attempts
  OPTIMISTIC_SEND_TIMEOUT_SECONDS: "0.5"
```

## Example: Complete Flow

```python
from sagaz import Saga
from sagaz.outbox import OutboxEvent, OptimisticPublisher
from sagaz.storage import PostgreSQLStorage
from sagaz.outbox.storage import PostgreSQLOutboxStorage
from sagaz.outbox.brokers import KafkaBroker

# Setup
saga_storage = PostgreSQLStorage("postgresql://localhost/db")
outbox_storage = PostgreSQLOutboxStorage("postgresql://localhost/db")
broker = KafkaBroker(bootstrap_servers="localhost:9092")
publisher = OptimisticPublisher(outbox_storage, broker, enabled=True)

# Execute saga and publish event
async def process_order(order_id: str, amount: float):
    # 1. Execute saga
    saga = OrderSaga()
    result = await saga.execute(order_id=order_id, amount=amount)
    
    # 2. Transaction: Save saga state + outbox event
    async with saga_storage.db.transaction():
        await saga_storage.save(saga)
        
        event = OutboxEvent(
            saga_id=saga.saga_id,
            event_type="OrderCreated",
            aggregate_type="order",
            aggregate_id=order_id,
            payload={
                "order_id": order_id,
                "amount": amount,
                "saga_id": saga.saga_id,
                "status": saga.status
            }
        )
        await outbox_storage.insert(event)
    
    # 3. Optimistic publish (after commit)
    success = await publisher.publish_after_commit(event)
    
    return {
        "saga_id": saga.saga_id,
        "order_id": order_id,
        "published_immediately": success
    }
```

## Summary

**Key Points:**
- ✅ 10x latency improvement in happy path
- ✅ Zero risk - failures handled automatically
- ✅ Feature flag for safe rollout
- ✅ Full metrics and monitoring
- ✅ Production-tested pattern

**When to Use:**
- ✅ Latency-sensitive applications
- ✅ High-throughput systems
- ✅ Stable infrastructure

**When NOT to Use:**
- ❌ Unstable broker (>10% failures)
- ❌ Already meeting SLA without it
- ❌ Debugging message delivery issues

**Next Steps:**
- Enable in staging environment
- Monitor success rate metrics
- Gradually roll out to production
- Set up alerts for high failure rate
